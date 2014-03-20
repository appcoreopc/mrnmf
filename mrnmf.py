"""
   Copyright (c) 2014, Austin R. Benson, David F. Gleich, 
   Purdue University, and Stanford University.
   All rights reserved.
 
   This file is part of MRNMF and is under the BSD 2-Clause License, 
   which can be found in the LICENSE file in the root directory, or at 
   http://opensource.org/licenses/BSD-2-Clause
"""

import sys
import os
import time
import random
import struct

import util
import dumbo
import dumbo.backends.common
from dumbo import opt

import numpy as np

"""
This file contains the main implementations of the MapReduce code.
"""

# some variables
ID_MAPPER = 'org.apache.hadoop.mapred.lib.IdentityMapper'
ID_REDUCER = 'org.apache.hadoop.mapred.lib.IdentityReducer'

class DataFormatException(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)


def starter_helper(prog):
    print 'running starter!'

    mypath = os.path.dirname(__file__)
    print 'my path: ' + mypath    

    prog.addopt('file', os.path.join(mypath, 'util.py'))
    prog.addopt('file', os.path.join(mypath, 'mrnmf.py'))

    splitsize = prog.delopt('split_size')
    if splitsize is not None:
        prog.addopt('jobconf',
            'mapreduce.input.fileinputformat.split.minsize=' + str(splitsize))

    prog.addopt('overwrite', 'yes')
    prog.addopt('jobconf', 'mapred.output.compress=true')
    prog.addopt('memlimit', '8g')

    mat = prog.delopt('mat')
    if mat:
        # add numreps copies of the input
        numreps = prog.delopt('repetition')
        if not numreps:
            numreps = 1
        for i in range(int(numreps)):
            prog.addopt('input',mat)
    
        return mat            
    else:
        return None


"""
MatrixHandler reads data and collects it
"""
class MatrixHandler(dumbo.backends.common.MapRedBase):
    def __init__(self):
        self.ncols = None
        self.unpacker = None
        self.nrows = 0
        self.deduced = False

    def collect(self, key, value):
        pass

    def collect_data_instance(self, key, value):
        if isinstance(value, str):
            if not self.deduced:
                self.deduced = self.deduce_string_type(value)
                # handle conversion from string
            if self.unpacker is not None:
                value = self.unpacker.unpack(value)
            else:
                value = [float(p) for p in value.split()]
        # check for numpy 2d array
        elif isinstance(value, np.ndarray):
            # verify column size
            if value.ndim == 2:
                # it's a block
                if self.ncols == None:
                    self.ncols = value.shape[1]
                if value.shape[1] != self.ncols:
                    raise DataFormatException(
                        'Number of columns in value did not match number of columns in matrix')
                for row in value:
                    row = row.tolist()
                    self.collect_data_instance(key, row)
                return
            else:
                value = value.tolist() # convert and continue below
        # check for list of lists
        elif isinstance(value, list):
            if len(value) > 0 and isinstance(value[0], list):
                if self.ncols == None:
                    self.ncols = len(value[0])
                    print >>sys.stderr, 'Matrix size: %i columns' % (self.ncols)
                if len(value[0]) != self.ncols:
                    raise DataFormatException(
                        'Number of columns in value did not match number of columns in matrix')
                for row in value:
                    self.collect_data_instance(key, row)
                return

        if self.ncols == None:
            self.ncols = len(value)
            print >>sys.stderr, 'Matrix size: %i columns' % (self.ncols)
        if len(value) != self.ncols:
            raise DataFormatException(
                'Length of value did not match number of columns')
        self.collect(key, value)

    def collect_data(self, data, key=None):
        if key == None:
            for key, value in data:
                self.collect_data_instance(key, value)
        else:
            for value in data:
                self.collect_data_instance(key, value)

    def deduce_string_type(self, val):
        # first check for TypedBytes list/vector
        try:
            [float(p) for p in val.split()]
        except:
            if len(val) == 0:
                return False
            if len(val) % 8 == 0:
                ncols = len(val) / 8
                # check for TypedBytes string
                try:
                    val = list(struct.unpack('d' * ncols, val))
                    self.unpacker = struct.Struct('d' * ncols)
                    return True
                except struct.error, serror:
                    # no idea what type this is!
                    raise DataFormatException('Data format type is not supported.')
            else:
                raise DataFormatException('Number of data bytes (%d)' % len(val)
                                          + ' is not a multiple of 8.')
        return True

class NMFMap(MatrixHandler):
    def __init__(self, blocksize=5, projsize=400,
                 compute_GP=True,
                 compute_QR=True,
                 compute_colnorms=True):
        MatrixHandler.__init__(self)
        self.blocksize = blocksize

        self.compute_GP = compute_GP
        self.data = []
        self.projsize = projsize
        self.A_curr = None

        self.compute_QR = compute_QR
        if compute_QR:
            self.qr_data = []

        self.compute_colnorms = compute_colnorms
        self.colnorms = None


    def QR(self):
        data = np.array(self.data)
        if len(self.qr_data) > 0:
            data = np.vstack((np.array(self.qr_data), data))
        return np.linalg.qr(data, 'r')
    
    def compress(self):
        if self.ncols is None or len(self.data) == 0:
            return

        if self.compute_GP:
            t0 = time.time()
            G = np.random.randn(self.projsize, len(self.data)) / 100.
            A_flush = G * np.mat(self.data)
            dt = time.time() - t0
            self.counters['numpy time (millisecs)'] += int(1000 * dt)

            # Add flushed update to local copy
            if self.A_curr == None:
                self.A_curr = A_flush
            else:
                self.A_curr += A_flush

        if self.compute_QR:
            t0 = time.time()
            R = self.QR()
            dt = time.time() - t0
            self.counters['numpy time (millisecs)'] += int(1000 * dt)
            # reset data and re-initialize to R
            self.qr_data = []
            for row in R:
                self.qr_data.append(util.array2list(row))

        self.data = []
                        
    def collect(self, key, value):
        self.data.append(value)
        self.nrows += 1
        
        if self.compute_colnorms:
            if self.colnorms == None:
                self.colnorms = np.abs(np.array(value))
            else:
                self.colnorms += np.abs(np.array(value))

        if len(self.data) > self.blocksize * self.ncols:
            self.counters['compressions'] += 1
            # compress the data
            self.compress()
            
        # write status updates so Hadoop doesn't complain
        if self.nrows % 50000 == 0:
            self.counters['rows processed'] += 50000

    def close(self):
        self.counters['rows processed'] += self.nrows % 50000
        self.compress()

        if self.compute_GP:
            if self.A_curr != None:
                for ind, row in enumerate(self.A_curr.getA()):
                    yield ('GP', ind), util.array2list(row)
        
        if self.compute_QR:
            for i, row in enumerate(self.qr_data):
                key = np.random.randint(0, 4000000000)
                yield ('QR', key), row

        if self.compute_colnorms and self.colnorms != None:
            for ind, val in enumerate(self.colnorms):
                yield ('colnorms', ind), val

    def __call__(self, data):
        self.collect_data(data)

        # finally, output data
        for key, val in self.close():
            yield key, val

class NMFReduce(MatrixHandler):
    def __init__(self, blocksize=3, isfinal=False):
        MatrixHandler.__init__(self)
        self.rowsums = {}
        self.colnorms = {}
        self.data = []
        self.blocksize = blocksize
        self.ncols = None
        self.isfinal = isfinal
        self.num_keys = 0

    def QR(self):
        return np.linalg.qr(np.array(self.data), 'r')

    def compress(self):
        # Compute a QR factorization on the data accumulated so far.
        if self.ncols == None or len(self.data) < self.ncols:
            return

        t0 = time.time()
        R = self.QR()
        dt = time.time() - t0

        # reset data and re-initialize to R
        self.data = []
        for row in R:
            self.data.append(util.array2list(row))

    def handle_GP(self, key, value):
        if key not in self.rowsums:
            self.rowsums[key] = value
        else:
            if len(value) != len(self.rowsums[key]):
                print >>sys.stderr, 'value: ' + str(value)
                print >>sys.stderr, 'value: ' + str(self.rowsums[key])
                raise DataFormatException('Differing array lengths for summing')
            for k in xrange(len(self.rowsums[key])):
                self.rowsums[key][k] += value[k]

    def handle_QR(self, key, value):
        if self.ncols == None:
            self.ncols = len(value)
        self.data.append(value)
        if len(self.data) > self.blocksize * self.ncols:
            self.compress()

    def handle_colnorms(self, key, values):
        self.colnorms[key] = sum(values)

    def close(self):
        self.compress()

        # Emit row sums for GP
        for key in self.rowsums:
            yield ('GP', key), self.rowsums[key]

        # Emit R factor of QR
        if self.isfinal:
            for i, row in enumerate(self.data):
                yield ('QR', i), row
        else:
            for i, row in enumerate(self.data):
                key = np.random.randint(0, 4000000000)
                yield ('QR', key), row

        # Emit column sums
        for key in self.colnorms:
            yield ('colnorms', key), self.colnorms[key]

    def __call__(self, data):
        for key, values in data:
            self.num_keys += 1
            if not (self.num_keys % 50000):
                self.counters['keys processed'] += 50000

            if key[0] == 'GP':
                for val in values:
                    self.handle_GP(key[1], val)
            elif key[0] == 'QR':
                for val in values:
                    self.handle_QR(key[1], val)
            elif key[0] == 'colnorms':
                self.handle_colnorms(key[1], values)
            else:
                raise DataFormatException('unknown key type: %s' % str(key[0]))

        for key, val in self.close():
            yield key, val

@opt("getpath", "yes")
class NMFParse():
    def __init__(self):
        pass

    def __call__(self, data):
        for key, values in data:
            for val in values:
                yield key, val

