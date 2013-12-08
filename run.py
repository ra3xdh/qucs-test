

import argparse
import difflib
import numpy as np
import os
import pprint
import subprocess
import shutil
import sys
import threading
import time

import parse_result as parse


# Add colors to the print messages
class bcolors:
    HEADER = '\033[95m'    # magenta
    OKBLUE = '\033[94m'    # blue
    OKGREEN = '\033[92m'   # green
    WARNING = '\033[93m'   # yellow
    FAIL = '\033[91m'      # red
    ENDC = '\033[0m'

# Avoid color codes if output piped to file
def pb(message):
    if sys.stdout.isatty():
        return bcolors.OKBLUE + message + bcolors.ENDC
    else:
        return message

def pg(message):
    if sys.stdout.isatty():
        return bcolors.OKGREEN + message + bcolors.ENDC
    else:
        return message

def pr(message):
    if sys.stdout.isatty():
        return bcolors.FAIL + message + bcolors.ENDC
    else:
        return message

def py(message):
    if sys.stdout.isatty():
        return bcolors.WARNING + message + bcolors.ENDC
    else:
        return message


#http://stackoverflow.com/questions/1191374/subprocess-with-timeout
class Command(object):
    def __init__(self, cmd):
        self.cmd = cmd
        self.process = None
        self.timeout = False
        self.retcode = 0

    def run(self, timeout):
        def target():
            print pb('Thread started')
            self.process = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = self.process.communicate()
            # keep the stdout and stderr
            self.out = out
            self.err = err
            print pb('Thread finished')

        thread = threading.Thread(target=target)
        thread.start()

        thread.join(timeout)
        if thread.is_alive():
            self.timeout = True
            print pr('Terminating process, timed out %i s' %timeout)
            self.process.terminate()
            thread.join()
        self.retcode =  self.process.returncode
        if self.retcode:
            print pr('  Return code: %i' %self.retcode)
        else:
            print pb('  Return code: %i' %self.retcode)



def get_subdirs(dir):
    '''
    Return a list of names of subdirectories.
    input : dir to look up for subdirs.
    '''
    return [name for name in os.listdir(dir)
            if os.path.isdir(os.path.join(dir, name))]


def check_netlist(ref_netlist, output_netlist, skip=1, verbose=0):
    '''
    Does a diff with reference netlist and a test netlist.

    input  : reference netlist
    input  : test output netlist
    output : diff status, different lines
    '''
    # http://docs.python.org/2.7/library/difflib.html
    net_equal = True
    bad_lines = []
    with open(ref_netlist) as f, open(output_netlist) as g:

        flines = f.readlines()
        glines = g.readlines()

        d = difflib.Differ()

        # skip first line?
        diff = list(d.compare(flines[skip:], glines[skip:]))

        # show complete diff?
        if verbose:
            print ' '.join(diff)

        for line in diff:
            # look in diff for code [+ - ?]: unique to f, unique to g or not present in f or g
            chars = set('+-?')
            if any((c in chars for c in line[:1])):
                net_equal = False
                #print line
                bad_lines.append(line)
        return net_equal, bad_lines


def run_schematic_to_netlist(proj, net_report={}, prefix='', init_test=False):
    '''
    Run Qucs to pererform the schematic -> netlist conversion.

    input  : test directory
    input  : dictionary for the testsuite
    output : dictionary reporting/updating issues
    '''

    #project dir
    name = proj.split(os.sep)[-1]

    print name

    # FIXME fail if the project name has underscore
    sim_types= ['DC_', 'AC_', 'TR_', 'SP_', 'SW_']
    for sim in sim_types:
        if sim in name:
            name=name[3:]

    name = name[:-4]
    print name

    tests_dir = os.getcwd()
    #print tests_dir

    proj_dir = os.path.join(tests_dir, 'testsuite', proj)
    print '\nProject : ', proj_dir

    # step into project
    os.chdir(proj_dir)

    input_sch = name+".sch"

    print 'Input: ', input_sch

    # have schematic to convert
    if os.path.isfile(input_sch):

        # either create reference netlist, initialize a test-project
        # or create a test-netlist to compare with existing reference netlist
        if init_test:
            print pb("Add test, creating reference netlist")
            output_netlist = "netlist.txt"
        else:
            output_netlist = "test_"+name+"_netlist.txt"

        cmd = [prefix + "qucs", "-n", "-i", input_sch, "-o", output_netlist]
        print 'Running : ', ' '.join(cmd)

        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        retval = p.wait()
        # report issues if any
        if retval:
            print 'Return code: ', retval
            for line in p.stdout.readlines():
                print line,

        # if not initializing the added test, compare netlists
        if not init_test:
            ###
            # netlist check
            # - if reference netlist provided, diff compare with test netlist
            # - report if missing
            ###
            ref_netlist = 'netlist.txt'
            if os.path.isfile(ref_netlist):
                print 'Comparing : diff %s %s' %(ref_netlist, output_netlist)
                net_equal, bad_lines = check_netlist(ref_netlist, output_netlist)

                if net_equal:
                    print pg('Diff     : PASS')
                else:
                    print pr('Diff     : FAIL')

                # collect things that are different
                if not net_equal:
                    net_report[proj] = bad_lines
            else:
                net_report[proj] = 'missing reference [netlist.txt]'

        # step out
        os.chdir(tests_dir)

    return net_report


def run_simulation(proj, sim_report={}, prefix='', init_test=False):
    '''
    Run simulation from reference netlist and compare outputs (dat, log)
    '''

    #name = proj.split('_')[-2]
    #project dir
    name = proj.split(os.sep)[-1]

    print name

    # FIXME fail if the project name has underscore
    sim_types= ['DC_', 'AC_', 'TR_', 'SP_', 'SW_']
    for sim in sim_types:
        if sim in name:
            name=name[3:]

    name = name[:-4]
    print name

    tests_dir = os.getcwd()

    proj_dir = os.path.join(tests_dir, 'testsuite', proj)
    print '\nProject : ', proj_dir

    # cd into project
    os.chdir(proj_dir)

    input_net = "netlist.txt"

    if os.path.isfile(input_net):

        #TODO get the DataSet field from the schematic file
        schematic = os.path.join(proj_dir,name+'.sch')
        #print 'schematic', schematic
        with open(schematic) as fp:
            for line in fp:
                if 'DataSet' in line:
                    # DataSet filename, no quotes
                    ref_dataset = line.split('=')[-1][:-2]


        print 'ref_dataset', ref_dataset

        if init_test:
            output_dataset = ref_dataset
        else:
            output_dataset = "test_"+name+".dat"

        cmd = [prefix + "qucsator", "-i", input_net, "-o", output_dataset]
        print 'Running : ', ' '.join(cmd)

        # TODO run a few times, record average, add to report
        tic = time.clock()

        # call the solver in a subprocess, set the timeout
        command = Command(cmd)
        command.run(timeout=5)
        toc = time.clock()

        runtime = toc - tic

        print pb('Runtime: %f' %runtime)


        # if adding test-project just save the log
        if init_test:
            # save log.txt
            # FIXME note that Qucs-gui adds a timestamp to the the log
            #       running Qucsator it does not the same header/footer
            logout = 'log.txt'
            print pb('Initializing %s saving: \n   %s/%s' %(proj, proj_dir, logout))
            with open(logout, 'w') as myFile:
                myFile.write(command.out)

            if (command.timeout):
                errout = 'error_timeout.txt'
                print pr('Failed initializaton of %s saving: \n   %s/%s' %(proj, proj_dir, errout))
                with open(errout, 'w') as myFile:
                    myFile.write(command.err)

            if (command.retcode):
                errout = 'error_code.txt'
                print pr('Failed initializaton of %s saving: \n   %s/%s' %(proj, proj_dir, errout))
                with open(errout, 'w') as myFile:
                    myFile.write(command.err)


        # perform comparison
        else:
            if not os.path.isfile(ref_dataset):
                os.exit(pr('bad, missing ref output'))

            # TODO failed also catches if the solver didn't run, output_dataset will be empty,
            # it will fail the comparison

            # let's compare results

            # list of failed variable comparisons
            failed=[]
            if not command.timeout:
                print pb('load data %s' %(ref_dataset))
                ref_data = parse.parse_file(ref_dataset)

                print pb('load data %s' %(output_dataset))
                test_data = parse.parse_file(output_dataset)

                #print ref_data['variables']

                print pb('Comparing dependent variables')

                for name, kind in ref_data['variables'].items():
                    if kind == 'dep':
                        #print name
                        ref_trace  = ref_data[name]
                        test_trace = test_data[name]

                        if not np.allclose(ref_trace, test_trace, rtol=1.00001e10, atol=1e-8):
                            print pr('  Failed %s' %(name))
                            failed.append(name)
                        else:
                            print pg('  Passed %s' %(name))


            # keep list of variables that failed comparison
            if failed:
                sim_report[proj] = [failed]

            # mark project as timed out
            if command.timeout:
                sim_report[proj] = ['timed out']


            # In case of failure or timeout, save the log and error ouputs
            if (failed or command.timeout):

                logout = 'fail_log.txt'
                print pr('failed %s saving: \n   %s/%s' %(proj, proj_dir, logout))
                with open(logout, 'w') as myFile:
                    myFile.write(command.out)

                errout = 'fail_error.txt'
                print pr('failed %s saving: \n   %s/%s' %(proj, proj_dir, errout))
                with open(errout, 'w') as myFile:
                    myFile.write(command.err)

        # TODO add timestamp into qucsator. Or time the call.
        # qucs creates the log.txt with time start and time end.

        # step out
        os.chdir(tests_dir)

    return sim_report


def add_test_project(sch):
    '''

    '''

    # get basename
    sch_name = os.path.basename(sch)[:-4]


    # scan schematic for types of simulation [.DC, .AC, .TR, .SP, .SW]
    #  skip if no simulaiton found, subcircuit?
    sim_types= ['.DC', '.AC', '.TR', '.SP', '.SW']
    schematic = open(sch).read()
    sim_found=''
    for sim in sim_types:
        if sim in schematic:
            #skip dot
            sim_found+=sim[1:]+'_'
    #print sim_found

    if not sim_found:
        sys.exit( pr('This schematic performs no simulation, is it a subcircuit?'))

    # create dir, concatenate simulation type(s), schematic name, append '_prj'
    dest = sim_found + sch_name + '_prj'
    print dest

    # scan for subcircuits, to be copied over destination Sub, filename=split(' ')[-2]
    sub_files=[]
    with open(sch) as fp:
        for line in fp:
            if '<Sub ' in line:
                # subcircuit filename, no quotes
                sub_file = line.split(' ')[-2][1:-1]
                if sub_file not in sub_files:
                    sub_files.append(sub_file)
    print 'subcircuits', sub_files

    dest_dir = os.path.join(os.getcwd(),'testsuite', dest)
    if not os.path.exists(dest_dir):
        print 'creating ', dest_dir
        os.makedirs(dest_dir)


    # copy schematic and needed subcircuit
    shutil.copy2(sch, dest_dir)

    for sub in sub_files:
        src = os.path.join(os.path.dirname(sch),sub)

        if os.path.isfile(src):
            shutil.copy2(src, dest_dir)
        else:
            sys.exit(pr('Oops, subcircuit not found: ', src))

    # bootstrap the netlist.txt
    run_schematic_to_netlist(dest_dir, prefix=prefix, init_test=True)

    # bootstrap the result.dat, log.txt
    run_simulation(dest_dir, prefix=prefix, init_test=True)


    # ready to test-fire, run.py and check --qucs, --qucsator
    # reminder to add to repository
    return


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Qucs testing script.')

    parser.add_argument('--prefix', type=str,
                       help='prefix of installed Qucs (default: /usr/local/)')

    parser.add_argument('--qucs',
                       action='store_true',
                       help='run qucs tests')

    parser.add_argument('--qucsator',
                       action='store_true',
                       help='run qucsator tests')

    parser.add_argument('--add-test', type=str,
                       help='add schematic to the testsuite')

    args = parser.parse_args()
    print(args)


    # TODO improve the discovery of qucs, qucator

    if args.prefix:
        #prefix = os.path.join(args.prefix, 'bin', os.sep)
        prefix = args.prefix
    else:
        # TODO add default paths, build location, system locations
        prefix = os.path.join('/usr/local/bin/')

    if os.path.isfile(os.path.join(prefix, 'qucsator')):
        print pb('Found Qucs in: %s' %(prefix))
    else:
        sys.exit(pr('Oh dear, Qucs not found in: %s' %(prefix)))


    print '\n'
    print pb('******************************************')
    print pb('** Test suite - Projects to be run      **')
    print pb('******************************************')
    testsuite = get_subdirs('./testsuite/')
    pprint.pprint(testsuite)


    if args.qucs:
        print '\n'
        print pb('******************************************')
        print pb('** Test schematic to netlist conversion **')
        print pb('******************************************')

        # loop over testsuite
        # messages are added to the dict, project as key
        net_report = {}
        for test in testsuite:
            net_report =  run_schematic_to_netlist(test, net_report)


        print '\n'
        print pb('############################################')
        print pb('#  Report schematic to netlist conversion  #')
        if net_report.keys():
            print pr('--> Found differences (!)')
            pprint.pprint(net_report)
        else:
            print pg('--> No differences found.')

    if args.qucsator:
        print '\n'
        print pb('********************************')
        print pb('** Test simulation and output **')
        print pb('********************************')

        # loop over testsuite
        # messages are added to the dict, project as key
        sim_report = {}
        for test in testsuite:
            sim_report = run_simulation(test, sim_report, prefix)


        print '\n'
        print pb('############################################')
        print pb('#  Report simulation result comparison     #')
        if sim_report.keys():
            print pr('--> Found numerical differences (!)')
            pprint.pprint(sim_report)
        else:
            print pg('--> No significant numerical differences found.')

    if args.add_test:
        print '\n'
        print py('********************************')
        print 'adding schematic: %s' %(args.add_test)

        sch = args.add_test

        add_test_project(sch)



    print '\n'
    print pb('###############  Done ######################')

