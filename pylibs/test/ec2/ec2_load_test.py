""" This functional test may be run under nosetests or by running this
module directly. When running under nosetests, The following
environment variables can be set to control test behavior and set ec2
connection parameters, in lieu of the command line options available
when run directly:

AWS_KEY                 -- your amazon key 
AWS_SECRET_KEY          -- your amazon secret key
AWS_SSH_KEY             -- your amazon ssh key name
AWS_SSH_KEY_PATH        -- path on disk to ssh key file

EC2_AMI                 -- your AMI name. AMI must have erlang R12B-1 or 
                           better, ruby, rake, python 2.5.1 or better, and
                           thrift installed
EC2_INSTANCE_TYPE       -- type of EC2 instances to start
EC2_INSTANCES           -- number of EC2 instances to start
EC2_RUN_TIME            -- length of time to run the load test
EC2_CLIENTS_PER_HOST    -- number of clients per instance
EC2_GET_THRESHOLD       -- If 99.9% of gets are not faster than this # of
                           milliseconds, the test fails
EC2_PUT_THRESHOLD       -- If 99.9% of puts are not faster than this # of
                           milliseconds, the test fails
EC2_DYNOMITE_BUILD_DIR  -- Directory to upload to and build in, on each
                           ec2 instance.
EC2_DYNOMITE_ARGS       -- Extra args to pass to dynomite start script
EC2_DYNOMITE_STORAGE    -- Dynomite storage module to use
EC2_LOAD_SCRIPT_ARGS    -- Extra args for load_thrift script
EC2_RAKE_ARGS           -- Extra args for rake (when building dynamo on each
                           ec2 instance)
EC2_SEPARATE_CLIENT     -- (flag) If true, run clients on separate instances
                           from servers. Default is to run both client and
                           server on same instance.
"""
import os
import sys
import boto
import subprocess
import time
from optparse import OptionParser
from random import choice
import cPickle as pickle

# Path to erl_call binary. FIXME! There must
# be a better way to do this.
EC = '/usr/local/lib/erlang/lib/erl_interface-3.5.9/bin'

def load_test(conf=None):
    if conf is None:
        conf = configure()
    ec2 = start_ec2(conf)
    try:
        wait_for_instances(conf, ec2)
        start_load(conf, ec2)
        wait(conf)
        stats = collect_stats(conf, ec2)
    finally:
        print "Stopping ec2 instances"
        ec2.stop_all()
    evaluate_stats(conf, stats)


def main():
    conf = configure(sys.argv)
    load_test(conf)
    

def start_ec2(conf):
    print "Connecting to ec2"
    conn = boto.connect_ec2(conf.aws_key, conf.aws_secret_key)
    print "Retrieving image", conf.ec2_ami
    ami = conn.get_image(conf.ec2_ami)
    if conf.separate_client:
        inst_count = conf.ec2_instances * 2
    else:
        inst_count = conf.ec2_instances
    print "Starting %s %s instances" % (inst_count, conf.ec2_type)
    res = ami.run(inst_count, inst_count,
                  key_name=conf.aws_ssh_key, instance_type=conf.ec2_type)
    return res


def start_load(conf, ec2):
    if conf.separate_client:
        host = '--host %s' % pick_host(ec2.instances)
    else:
        host = ''    
    for _, instance in enumerate_clients(conf, ec2.instances):
        remote(conf, instance, "cd %s/pylibs; "
               "PYTHONPATH=. ./tools/load_thrift.py "
               "--log /tmp/stats.pickle --clients %s %s %s &"
               % (conf.dyn_dir, conf.ec2_clients, host, conf.load_args))
        print "Load started on %s %s" % (instance, host)


def wait(conf):
    print "Running load on all instances for %s seconds" % conf.ec2_run_time
    time.sleep(conf.ec2_run_time)


def collect_stats(conf, ec2):
    stats = {'collisions': 0,
             'get': [],
             'put': []}
    for ix, instance in enumerate_clients(conf, ec2.instances):
        stats_file = "/tmp/%s.stats" % ix
        print "Collecting stats from %s into %s" % (instance, stats_file)
        cmd = ['scp', '-C', '-i', conf.aws_ssh_key_path,
               'root@%s:/tmp/stats.pickle' % instance.public_dns_name,
               stats_file]
        p = subprocess.Popen(cmd,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (out, err) = p.communicate()
        if p.returncode != 0:
            print "failed to collect stats from %s: %s/%s" % (instance,
                                                              out, err)
            continue
        print "Collected"
        sf = open(stats_file, 'r')
        batch = pickle.load(sf)
        sf.close()
        stats['collisions'] += batch['collisions']
        stats['get'].extend(batch['get'])
        stats['put'].extend(batch['put'])
    return stats
    

def evaluate_stats(conf, stats):
    g = stats['get'][:]
    g.sort()
    p = stats['put'][:]
    p.sort()
    gets = len(g)
    puts = len(p)

    get99 = g[int(gets * .999)-1] * 1000
    put99 = p[int(puts * .999)-1] * 1000

    print "gets: %d puts: %d collisions: %d" \
          % (gets, puts, stats['collisions'])
    print "get avg: %f0.3ms median: %f0.3ms 99.9: %f0.3ms" % (
        (sum(g) / float(gets)) * 1000,
        (g[gets/2]) * 1000,
        get99)
    print "put avg: %f0.3ms median: %f0.3ms 99.9: %f0.3ms" % (
        (sum(p) / float(puts)) * 1000,
        (p[puts/2]) * 1000,
        put99)

    print "gets:"
    for pct in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100):
        gp = g[int(gets * float(pct)/100.0)-1] * 1000
        print " %3d%% < %7.3fms" % (pct, gp)

    print "puts:"
    for pct in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100):
        pp = p[int(puts * float(pct)/100.0)-1] * 1000
        print " %3d%% < %7.3fms" % (pct, pp)
    
    assert get99 <= conf.get_threshold, "Get timings too slow (%s > %s)" % (
        get99, conf.get_threshold)
    assert put99 <= conf.put_threshold, "Put timings too slow (%s > %s)" % (
        put99, conf.put_threshold)
    

def wait_for_instances(conf, ec2):
    ready = {}
    client_ready = {}
    while True:
        pending = []
        running = {}
        for i in ec2.instances:
            print i, i.state
            if i.state == 'pending':
                i.update()
            if i.state == 'pending':
                pending.append(i)
            elif i.state == 'running':
                running[i.id] = i
            else:
                print "Unexpected state for instance %s: %s" % (i, i.state)
                pending.append(i)
        if conf.separate_client:
            print "Waiting for instance startup: " \
                  "%s pending %s running %s ready %s client ready" \
                  % (len(pending), len(running), len(ready), len(client_ready))
        else:
            print "Waiting for instance startup: " \
                  "%s pending %s running %s ready" \
                  % (len(pending), len(running), len(ready))
        if all_ready(conf, ec2, ready, client_ready):
            print "All %s instances ready" % (len(ready))
            break
        join = None
        for i in running.values():            
            if i.id in ready or i.id in client_ready:
                continue
            if ready:
                join = ready.values()[0].private_dns_name.split('.')[0]
                # FIXME can parallelize remaining starts
            if conf.separate_client and all_servers_ready(conf, ready):
                print "Servers are ready, loading %s clients" \
                      % conf.ec2_instances
                if ensure_uploaded(conf, i, make=False):
                    client_ready[i.id] = i
                    i.client = True
            elif ensure_dynomite_started(conf, i, join):
                ready[i.id] = i
        time.sleep(10)


def ensure_dynomite_started(conf, instance, join=None):
    if not ensure_uploaded(conf, instance):
        return False
    args = {
        'ec': EC,
        'dyn_dir': conf.dyn_dir,            
        'join': '',
        'storage': conf.dynomite_storage,
        'extra': conf.dynomite_args}
    if join is not None:
        print "Instance %s will join dynomite node at %s" % (instance, join)
        args['join'] = ' -j dynomite@%s' % join
                
    cmd = "%(dyn_dir)s/bin/dynomite status %(ec)s|| "\
          "%(dyn_dir)s/bin/dynomite start --storage %(storage)s " \
          "--data /tmp/dynomite_data --detach %(join)s %(extra)s" % args
    
    p = remote(conf, instance, cmd)
    (out, err) = p.communicate()
    if p.returncode != 0:
        print "%s is not ready %s/%s" % (instance, out, err)
        return False
    return True


def ensure_uploaded(conf, instance, make=True):    
    cmd = "ls %s" % conf.dyn_dir
    p = remote(conf, instance, cmd)
    (out, err) = p.communicate()
    if p.returncode != 0:
        if 'Connection refused' in err:
            print "%s sshd not ready" % instance
            return False
        print out, err
        return upload(conf, instance, make=make)
    return True
        

def upload(conf, instance, make=True):
    # FIXME this could be made more efficient by parallelizing it
    # do it in a worker thread or something, have a building list
    # and queue to push back done instances
    print "Uploading dynomite distribution to %s" % instance
    root = os.path.dirname(
        os.path.dirname(
        os.path.dirname(
        os.path.dirname(
        os.path.abspath(__file__)))))
    assert root.endswith('dynomite')
    cmd = ['rsync', '-avz', '-e', "ssh -i %s" % conf.aws_ssh_key_path,
           '--exclude', '*.beam', '--exclude', '.git', '--exclude', '.svn',
           '--exclude', 'etest/log', '--exclude', '*.egg',
           '%s/' % root,
           'root@%s:%s' % (instance.public_dns_name, conf.dyn_dir)]
    print ' '.join(cmd)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = p.communicate()
    if p.returncode != 0:
        print "Upload to %s failed" % instance
        print cmd
        print out
        print err
        raise Exception("Upload failed")
    if make:
        print "Building dynomite on %s" % instance
        r = remote(conf, instance,
                   'cd %s && rake %s' % (conf.dyn_dir, conf.rake_args))
        (out, err) = r.communicate()
        if r.returncode != 0:
            raise Exception("rake failed: %s/%s" % (out, err))
        return True


def remote(conf, instance, cmd):
    print instance, cmd
    return subprocess.Popen(['ssh', '-i', conf.aws_ssh_key_path,
                             '-o',  'StrictHostKeyChecking no',
                             'root@%s' % instance.public_dns_name,
                             cmd],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
                            

def configure(argv=None):
    if argv is None:
        argv = []

    env = os.environ
    parser = OptionParser()
    parser.add_option('--aws-key', '--key',
                      action='store', dest='aws_key',
                      default=env.get('AWS_KEY', None),
                      help='AWS key (the short one)')
    parser.add_option('--aws-secret-key', '--secret-key',
                      action='store', dest='aws_secret_key',
                      default=env.get('AWS_SECRET_KEY', None),
                      help='AWS secret key (the long one)')
    parser.add_option('--aws-ssh-key', '--ssh-key',
                      action='store', dest='aws_ssh_key',
                      default=env.get('AWS_SSH_KEY', None),
                      help='Name of AWS ssh key pair to use')
    parser.add_option('--aws-ssh-key-path', '--ssh-key-path',
                      action='store', dest='aws_ssh_key_path',
                      default=env.get('AWS_SSH_KEY_PATH', None),
                      help='Path on disk to AWS ssh private key file '
                      'associated with chosen ssh key pair name')
    parser.add_option('--ec2-ami', '--ami',
                      action='store', dest='ec2_ami',
                      default=env.get('EC2_AMI', None),
                      help='ID of the AMI to use when starting ec2 instances')
    parser.add_option('--ec2-type', '--type',
                      action='store', dest='ec2_type',
                      default=env.get('EC2_INSTANCE_TYPE', 'm1.small'),
                      help='Type of instances to start (default: m1.small)')
    parser.add_option('--ec2-instances', '--instances',
                      action='store', dest='ec2_instances', type="int",
                      default=env.get('EC2_INSTANCES', 4),
                      help='Number of instances to start (default: 4)')
    parser.add_option('--ec2-run-time', '--run-time',
                      action='store', dest='ec2_run_time', type="int",
                      default=env.get('EC2_RUN_TIME', 300),
                      help='Number of seconds to run the test (default: 300)')
    parser.add_option('--ec2-clients', '--clients',
                      action='store', dest='ec2_clients', type="int",
                      default=env.get('EC2_CLIENTS_PER_HOST', 10),
                      help='Number of client threads per host (default: 10)')
    parser.add_option('--get-threshold', 
                      action='store', dest='get_threshold', type="int",
                      default=env.get('EC2_GET_THRESHOLD', 300),
                      help='If 99.9% of gets are not faster than this # of '
                      'milliseconds, the test fails (default: 300)')
    parser.add_option('--put-threshold', 
                      action='store', dest='put_threshold', type="int",
                      default=env.get('EC2_PUT_THRESHOLD', 300),
                      help='If 99.9% of puts are not faster than this # of '
                      'milliseconds, the test fails (default: 300)')
    parser.add_option('--dynomite-build-dir', '--dynomite-dir',
                      action='store', dest='dyn_dir',
                      default=env.get('EC2_DYNOMITE_BUILD_DIR',
                                      '/tmp/dynomite'),
                      help='Directory to upload to and build in, on each '
                      'ec2 instance')
    parser.add_option('--dynomite-storage',
                      action='store', dest='dynomite_storage',
                      default=env.get('EC2_DYNOMITE_STORAGE', 'fs_storage'),
                      help='Dynomite storage module to use')
    parser.add_option('--dynomite-args',
                      action='store', dest='dynomite_args',
                      default=env.get('EC2_DYNOMITE_ARGS', ''),
                      help='Extra args to pass to dynomite start script '
                      'on each node')
    parser.add_option('--load-args',
                      action='store', dest='load_args',
                      default=env.get('EC2_LOAD_SCRIPT_ARGS', ''),
                      help='Extra args to pass to load script '
                      'on each node')
    parser.add_option('--rake-args',
                      action='store', dest='rake_args',
                      default=env.get('EC2_RAKE_ARGS', ''),
                      help='Extra args to pass to rake when building '
                      'dynomite on each node')
    parser.add_option('--separate-client',
                      action='store_true', dest='separate_client',
                      default=boolean(env.get('EC2_SEPARATE_CLIENT', False)),
                      help="Run clients on separate instances from servers")
    
    options, junk = parser.parse_args(argv)
    required = (('aws_key', '--aws-key', 'AWS_KEY'),
                ('aws_secret_key', '--aws-secret-key', 'AWS_SECRET_KEY'),
                ('aws_ssh_key', '--aws-ssh-key', 'AWS_SSH_KEY'),
                ('aws_ssh_key_path', '--aws-ssh-key-path', 'AWS_SSH_KEY_PATH'),
                ('ec2_ami', '--ec2-ami', 'EC2_AMI'))
    for (opt, oname, ename) in required:
        if not getattr(options, opt):
            parser.error("%s (%s) is required" % (oname, ename))

    return options


def all_ready(conf, ec2, ready, client_ready):
    if conf.separate_client:
        for instance in ec2.instances:
            if not instance.id in ready and not instance.id in client_ready:
                return False
    else:
        for instance in ec2.instances:
            if not instance.id in ready:
                return False
    return True


def all_servers_ready(conf, ready):
    return len(ready.keys()) == conf.ec2_instances


def boolean(val):
    if isinstance(val, basestring):
        return val.upper() in ['1', 'T', 'Y', 'TRUE', 'YES']
    return bool(val)


def enumerate_clients(conf, instances):
    if not conf.separate_client:
        for ix, instance in enumerate(instances):
            yield ix, instance
    ix = 0
    for instance in instances:
        if getattr(instance, 'client', False):
            yield ix, instance
            ix += 1


def pick_host(instances):
    servers = [i for i in instances if not getattr(i, 'client', False)]
    return choice(servers).private_dns_name


if __name__ == '__main__':
    main()
