#!/usr/bin/env dumbo

import sys
import os
import time
import random

import numpy as np
import struct

import util
import mrnmf

import dumbo
import dumbo.backends.common

# create the global options structure
gopts = util.GlobalOptions()

class Map:
  def __init__(self):
      #self.max_key = 40000
      self.mat = []
      with open('cells_example_1_40k.txt', 'r') as f:
          for line in f:
              row = [float(v) for v in line.split()]
              self.mat.append(row)

      self.mat = np.array(self.mat)
      #self.mat = self.mat[:self.max_key, :]
      print >>sys.stderr, self.mat.shape

  def __call__(self, key, value):
      #if key > self.max_key:
      #    return
      value = [float(v) for v in value]
      split_size = 1000
      total = self.mat.shape[0] / split_size
      for j in xrange(total):
          if j == total - 1:
              B = np.kron(np.array(value), self.mat[split_size * j:])
          else:
              B = np.kron(np.array(value), self.mat[split_size * j:split_size * (j + 1)])
          print >>sys.stderr, B.shape
          keys = [split_size * j + i + 1 for i in xrange(B.shape[0])]
          key = (key, keys)
          yield key, B.tolist()
          #for i, row in enumerate(B):
          #    key = [key, split_size * j + i + 1]
          #    val = [float(v) for v in row]
          #    print >>sys.stderr, len(val)
          #    yield key, struct.pack('d' * len(val), *val)

def runner(job):
    options=[('numreducetasks', '0'), ('nummaptasks', '40')]
    job.additer(mapper=Map(), reducer=mrnmf.ID_REDUCER, opts=options)

def starter(prog):
    print "running starter!"

    mypath =  os.path.dirname(__file__)
    print "my path: " + mypath

    # set the global opts
    gopts.prog = prog

    mat = prog.delopt('mat')
    if not mat:
        return "'mat' not specified'"

    prog.addopt('memlimit','8g')

    prog.addopt('file',os.path.join(mypath,'util.py'))
    prog.addopt('file',os.path.join(mypath,'mrnmf.py'))
    prog.addopt('file',os.path.join(mypath,'cells_example_1_40k.txt'))

    prog.addopt('input', mat)
    matname,matext = os.path.splitext(mat)

    output = prog.getopt('output')
    if not output:
        prog.addopt('output','%s-randn%s'%(matname,'.bseq'))

    prog.addopt('overwrite','yes')
    prog.addopt('jobconf','mapred.output.compress=true')

    gopts.save_params()

if __name__ == '__main__':
    dumbo.main(runner, starter)
