"""
This module implements the communication REST layer for the python <-> H2O connection.
"""

import os
import re
import urllib
from connection import H2OConnection
from job import H2OJob
from frame import H2OFrame
import h2o_model_builder


def import_file(path):
  """
  Import a single file or collection of files.

  :param path: A path to a data file (remote or local).
  :return: A new H2OFrame
  """
  paths = [path] if isinstance(path,str) else path
  return [ _import1(fname) for fname in paths ]

def _import1(path):
  j = H2OConnection.get_json(url_suffix="ImportFiles", path=path)
  if j['fails']:
    raise ValueError("ImportFiles of " + path + " failed on " + j['fails'])
  return j['keys'][0]

def upload_file(path, destination_key=""):
  """
  Upload a dataset at the path given from the local machine to the H2O cluster.

  :param path: A path specifying the location of the data to upload.
  :param destination_key: The name of the H2O Frame in the H2O Cluster.
  :return: A new H2OFrame
  """
  fui = {"file": os.path.abspath(path)}
  dest_key = H2OFrame.py_tmp_key() if destination_key == "" else destination_key
  H2OConnection.post_json(url_suffix="PostFile", file_upload_info=fui,destination_key=dest_key)
  return H2OFrame(text_key=dest_key)


def import_frame(path=None, vecs=None):
  """
  Import a frame from a file (remote or local machine). If you run H2O on Hadoop, you can access to HDFS

  :param path: A path specifying the location of the data to import.
  :return: A new H2OFrame
  """
  return H2OFrame(vecs=vecs) if vecs else H2OFrame(remote_fname=path)


def parse_setup(rawkey):
  """
  :param rawkey: A collection of imported file keys
  :return: A ParseSetup "object"
  """

  # So the st00pid H2O backend only accepts things that are quoted (nasty Java)
  if isinstance(rawkey, unicode): rawkey = [rawkey]
  j = H2OConnection.post_json(url_suffix="ParseSetup", source_keys=[_quoted(key) for key in rawkey])
  if not j['is_valid']:
    raise ValueError("ParseSetup not Valid", j)
  return j


def parse(setup, h2o_name, first_line_is_header=(-1, 0, 1)):
  """
  Trigger a parse; blocking; removeFrame just keep the Vec keys.

  :param setup: The result of calling parse_setup.
  :param h2o_name: The name of the H2O Frame on the back end.
  :param first_line_is_header: -1 means data, 0 means guess, 1 means header.
  :return: A new parsed object  
  """
  # Parse parameters (None values provided by setup)
  p = { 'destination_key' : h2o_name,
        'parse_type' : None,
        'separator' : None,
        'single_quotes' : None,
        'check_header'  : None,
        'number_columns' : None,
        'chunk_size'    : None,
        'delete_on_done' : True,
        'blocking' : True,
        'remove_frame' : True
  }
  if isinstance(first_line_is_header, tuple):
    first_line_is_header = 0

  if setup["column_names"]:
    setup["column_names"] = [_quoted(name) for name in setup["column_names"]]
    p["column_names"] = None

  if setup["column_types"]:
    setup["column_types"] = [_quoted(name) for name in setup["column_types"]]
    p["column_types"] = None

  if setup["na_strings"]:
    setup["na_strings"] = [_quoted(name) for name in setup["na_strings"]]
    p["na_strings"] = None


  # update the parse parameters with the parse_setup values
  p.update({k: v for k, v in setup.iteritems() if k in p})

  p["check_header"] = first_line_is_header

  # Extract only 'name' from each src in the array of srcs
  p['source_keys'] = [_quoted(src['name']) for src in setup['source_keys']]

  # Request blocking parse
  j = H2OJob(H2OConnection.post_json(url_suffix="Parse", **p), "Parse").poll()
  return j.jobs


def _quoted(key):
  is_quoted = len(re.findall(r'\"(.+?)\"', key)) != 0
  key = key if is_quoted  else "\"" + key + "\""
  return key

"""
Here are some testing utilities for running the pyunit tests in conjunction with run.py.

run.py issues an ip and port as a string:  "<ip>:<port>".
The expected value of sys_args[1] is "<ip>:<port>"
"""


"""
All tests MUST have the following structure:

import sys
sys.path.insert(1, "..")  # may vary depending on this test's position relative to h2o-py
import h2o


def my_test(ip=None, port=None):
  ...test filling...

if __name__ == "__main__":
  h2o.run_test(sys.argv, my_test)

So each test must have an ip and port
"""
def run_test(sys_args, test_to_run):
  ip, port = sys_args[2].split(":")
  test_to_run(ip, port)

def remove(key):
  """
  Remove key from H2O.

  :param key: The key pointing to the object to be removed.
  :return: Void
  """
  H2OConnection.delete("Remove", key=key)


def rapids(expr):
  """
  Fire off a Rapids expression.

  :param expr: The rapids expression (ascii string).
  :return: The JSON response of the Rapids execution
  """
  return H2OConnection.post_json("Rapids", ast=urllib.quote(expr))


def frame(key):
  """
  Retrieve metadata for a key that points to a Frame.

  :param key: A pointer to a Frame  in H2O.
  :return: Meta information on the frame
  """
  return H2OConnection.get_json("Frames/" + key)


def init(ip="localhost", port=54321):
  """
  Initiate an H2O connection to the specified ip and port.

  :param ip: A IP address, default is "localhost".
  :param port: A port, default is 54321.
  :return: None
  """
  H2OConnection(ip=ip, port=port)
  return None



def deeplearning(x,y,validation_x=None,validation_y=None,**kwargs):
  """
  Build a supervised Deep Learning model (kwargs are the same arguments that you can find in FLOW)
  """
  return h2o_model_builder.supervised_model_build(x,y,validation_x,validation_y,"deeplearning",kwargs)

def gbm(x,y,validation_x=None,validation_y=None,**kwargs):
  """
  Build a Gradient Boosted Method model (kwargs are the same arguments that you can find in FLOW)
  """
  return h2o_model_builder.supervised_model_build(x,y,validation_x,validation_y,"gbm",kwargs)

def glm(x,y,validation_x=None,validation_y=None,**kwargs):
  """
  Build a Generalized Linear Model (kwargs are the same arguments that you can find in FLOW)
  """
  return h2o_model_builder.supervised_model_build(x,y,validation_x,validation_y,"glm",kwargs)

def kmeans(x,validation_x=None,**kwargs):
  """
  Build a KMeans model (kwargs are the same arguments that you can find in FLOW)
  """
  return h2o_model_builder.unsupervised_model_build(x,validation_x,"kmeans",kwargs)

def ddply(frame,cols,fun):
  return frame.ddply(cols,fun)

def network_test():
  res = H2OConnection.get_json(url_suffix="NetworkTest")
  res["table"].show()

def locate(path):
  """
  Search for a relative path and turn it into an absolute path.
  This is handy when hunting for data files to be passed into h2o and used by import file.
  Note: This function is for unit testing purposes only.

  :param path: Path to search for
  :return: Absolute path if it is found.  None otherwise.
  """

  tmp_dir = os.path.realpath(os.getcwd())
  possible_result = os.path.join(tmp_dir, path)
  while (True):
      if (os.path.exists(possible_result)):
          return possible_result

      next_tmp_dir = os.path.dirname(tmp_dir)
      if (next_tmp_dir == tmp_dir):
          return None

      tmp_dir = next_tmp_dir
      possible_result = os.path.join(tmp_dir, path)
