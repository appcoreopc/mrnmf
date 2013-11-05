#!/usr/bin/env python

import os
import shutil
import subprocess
import sys
import time
import util
from optparse import OptionParser

parser = OptionParser()
parser.add_option('-i', '--input', dest='input', default='',
                  help='input matrix')
parser.add_option('-o', '--output', dest='out', default='',
                  help='base string for output of Hadoop jobs')
parser.add_option('-l', '--local_output', dest='local_out', default='.',
                  help='Base directory for placing local files')
parser.add_option('-t', '--times_output', dest='times_out', default='times',
                  help='file for storing command times')
parser.add_option('-H', '--hadoop', dest='hadoop', default='',
                  help='name of hadoop for Dumbo')
parser.add_option('-q', '--quiet', action='store_false', dest='verbose',
                  default=True, help='turn off some statement printing')

(options, args) = parser.parse_args()
cm = util.CommandManager(verbose=options.verbose)

local_out = options.local_out
out_file = lambda f: local_out + '/' + f
if not os.path.exists(local_out):
    os.mkdir(local_out)
hadoop = options.hadoop
in1 = options.input
out = options.out
if out == '':
    out = 'NMF_GP_TESTING'

out1 = out + '_1'
cm.run_dumbo('GaussianProjection.py', hadoop,
             ['-mat ' + in1, '-output ' + out1, '-reduce_schedule 40,1'])

# Copy columns locally
cols_file = out_file('cols.txt')
cm.copy_from_hdfs(out1, cols_file, delete=True)
cm.parse_seq_file(cols_file, cols_file + '.out')

out2 = out + '_2'
cm.run_dumbo('NNLS1.py', hadoop,
             ['-mat ' + in1, '-output ' + out2, '-cols_path ' + cols_file + '.out',
              '-reduce_schedule 40,1', '-libjar feathers.jar'])

# Copy WTW locally
WTW_file = out_file('wtw.txt')
cm.copy_from_hdfs(out2 + '/WTW', WTW_file, delete=True)
cm.parse_seq_file(WTW_file, WTW_file + '.out')

out3 = out + '_3'
cm.run_dumbo('NNLS2.py', hadoop,
             ['-mat ' + out2 + '/RHS', '-output ' + out3,
              '-wtw_path ' + WTW_file + '.out', '-libjar feathers.jar'])
