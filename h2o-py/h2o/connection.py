"""
An H2OConnection represents the latest active handle to a cloud. No more than a single
H2OConnection object will be active at any one time.
"""

import requests
import math
import re
import os
import sys
import time
import tempfile
import tabulate
import subprocess
import atexit
from two_dim_table import H2OTwoDimTable

__H2OCONN__ = None            # the single active connection to H2O cloud
__H2O_REST_API_VERSION__ = 3  # const for the version of the rest api


class H2OConnection(object):
  """
  H2OConnection is a class that represents a connection to the H2O cluster.
  It is specified by an IP address and a port number.

  Objects of type H2OConnection are not instantiated directly!

  This class contains static methods for performing the common REST methods
  GET, POST, and DELETE.
  """

  def __init__(self, ip="localhost", port=54321, size=1, start_h2o=False, enable_assertions=False,
               license=None, max_mem_size_GB=1, min_mem_size_GB=1, ice_root=None):
    """
        Instantiate the package handle to the H2O cluster.
    :param ip: An IP address, default is "localhost"
    :param port: A port, default is 54321
    :param size: THe expected number of h2o instances (ignored if start_h2o is True)
    :param start_h2o: A boolean dictating whether this module should start the H2O jvm. An attempt is made anyways if _connect fails.
    :param enable_assertions: If start_h2o, pass `-ea` as a VM option.s
    :param license: If not None, is a path to a license file.
    :param max_mem_size_GB: Maximum heap size (jvm option Xmx) in gigabytes.
    :param min_mem_size_GB: Minimum heap size (jvm option Xms) in gigabytes.
    :param ice_root: A temporary directory (default location is determined by tempfile.mkdtemp()) to hold H2O log files.
    :return: None
    """
    port = as_int(port)
    if not (isinstance(port, int) and 0 <= port <= sys.maxint):
       raise ValueError("Port out of range, "+port)
    global __H2OCONN__
    self._ip = ip
    self._port = port
    self._session_id = None
    self._rest_version = __H2O_REST_API_VERSION__
    self._child = getattr(__H2OCONN__, "_child") if hasattr(__H2OCONN__, "_child") else None
    __H2OCONN__ = self
    if start_h2o:
      if not ice_root:
        ice_root = tempfile.mkdtemp()
      cld = self._start_local_h2o_jar(max_mem_size_GB, min_mem_size_GB, enable_assertions, license, ice_root)
    else:
      try:
        cld = self._connect(size)
      except:
        # try to start local jar or re-raise previous exception
        print
        print
        print "No instance found at ip and port: " + ip + ":" + str(port) + ". Trying to start local jar..."
        print
        print
        if os.path.exists(os.path.join(sys.prefix, "h2o_jar/h2o.jar")):
          if not ice_root:
            ice_root = tempfile.mkdtemp()
          cld = self._start_local_h2o_jar(max_mem_size_GB, min_mem_size_GB, enable_assertions, license, ice_root)
        else:
          print "No jar file found. Could not start local instance."
          raise

    # self._session_id = self.get_session_id()
    ncpus = sum([n['num_cpus'] for n in cld['nodes']])
    allowed_cpus = sum([n['cpus_allowed'] for n in cld['nodes']])
    mmax = sum([n['max_mem'] for n in cld['nodes']])
    cluster_health = all([n['healthy'] for n in cld['nodes']])
    cluster_info = [
      ["H2O cluster uptime: ", get_human_readable_time(cld["cloud_uptime_millis"])],
      ["H2O cluster version: ", cld["version"]],
      ["H2O cluster name: ", cld["cloud_name"]],
      ["H2O cluster total nodes: ", cld["cloud_size"]],
      ["H2O cluster total memory: ", get_human_readable_size(mmax)],
      ["H2O cluster total cores: ", str(ncpus)],
      ["H2O cluster allowed cores: ", str(allowed_cpus)],
      ["H2O cluster healthy: ", str(cluster_health)],
    ]
    print
    print tabulate.tabulate(cluster_info)
    print

  def _connect(self, size, max_retries=5, print_dots=False):
    """
    Does not actually "connect", instead simply tests that the cluster can be reached,
    is of a certain size, and is taking basic status commands.
    :param size: The number of H2O instances in the cloud.
    :return: The JSON response from a "stable" cluster.
    """
    max_retries = max_retries
    retries = 0
    while True:
      retries += 1
      if print_dots:
        self._print_dots(retries)
      try:
        cld = H2OConnection.get_json(url_suffix="Cloud")
        if not cld['cloud_healthy']:
          raise ValueError("Cluster reports unhealthy status", cld)
        if cld['cloud_size'] >= size and cld['consensus']:
          if print_dots: print " Connection sucessful!"
          return cld
      except EnvironmentError:
        pass
      # Cloud too small or voting in progress; sleep; try again
      time.sleep(0.1)
      if retries > max_retries:
        raise EnvironmentError("Max retries exceeded. Could not establish link to the H2O cloud @ " + str(self._ip) + ":" + str(self._port))

  def _print_dots(self, retries):
    sys.stdout.write("\rStarting H2O JVM and connecting: {}".format("." * retries))
    sys.stdout.flush()

  def _start_local_h2o_jar(self, mmax, mmin, ea, license, ice):
    command = H2OConnection._check_java()
    if license:
      if not os.path.exists(license):
        raise ValueError("License file not found (" + license + ")")

    if not ice:
      raise ValueError("`ice_root` must be specified")

    stdout = open(H2OConnection._tmp_file("stdout"), 'w')
    stderr = open(H2OConnection._tmp_file("stderr"), 'w')

    print "Using ice_root: " + ice
    print

    jar_file = os.path.join(sys.prefix, "h2o_jar/h2o.jar")

    jver = subprocess.check_output([command, "-version"], stderr=subprocess.STDOUT)

    print
    print "Java Version: " + jver
    print

    if "GNU libgcj" in jver:
      raise ValueError("Sorry, GNU Java is not supported for H2O.\n"+
                       "Please download the latest Java SE JDK 7 from the following URL:\n"+
                       "http://www.oracle.com/technetwork/java/javase/downloads/jdk7-downloads-1880260.html")

    if "Client VM" in jver:
      print "WARNING: "
      print "You have a 32-bit version of Java. H2O works best with 64-bit Java."
      print "Please download the latest Java SE JDK 7 from the following URL:"
      print "http://www.oracle.com/technetwork/java/javase/downloads/jdk7-downloads-1880260.html"
      print

    vm_opts = ["-Xms{}g".format(mmin), "-Xmx{}g".format(mmax)]
    if ea:
      vm_opts += ["-ea"]

    h2o_opts = ["-jar", jar_file,
                "-name", "H2O_started_from_python",
                "-ip", "127.0.0.1",
                "-port", "54321",
                "-ice_root", ice,
                ]
    if license:
      h2o_opts += ["-license", license]

    cmd = [command] + vm_opts + h2o_opts

    cwd = os.path.abspath(os.getcwd())
    self._child = subprocess.Popen(args=cmd, stdout=stdout, stderr=stderr, cwd=cwd)
    cld = self._connect(1, 30, True)
    return cld

  @staticmethod
  def _check_java():
    # *WARNING* some over-engineering follows... :{

    # is java in PATH?
    if H2OConnection._pwhich("java"):
      return H2OConnection._pwhich("java")

    # check if JAVA_HOME is set (for windoz)
    if os.getenv("JAVA_HOME"):
      return os.path.join(os.getenv("JAVA_HOME"), "bin", "java.exe")

    # check /Program Files/ and /Program Files (x86)/ if os is windoz
    if sys.platform == "windows":
      program_folder = os.path.join("C:", "{}", "Java")
      program_folders = [program_folder.format("Program Files"),
                         program_folder.format("Program Files (x86)")]

      # check both possible program files...
      for folder in program_folders:

        # hunt down the jdk directory
        possible_jdk_dir = [d for d in folder if 'jdk' in d]

        # if got a non-empty list of jdk directory candidates
        if len(possible_jdk_dir) != 0:

          # loop over and check if the java.exe exists
          for jdk in possible_jdk_dir:
            path = os.path.join(folder, jdk, "bin", "java.exe")
            if os.path.exists(path):
              return path

      # check for JRE and warn
      for folder in program_folders:
        path = os.path.join(folder, "jre7", "bin", "java.exe")
        if os.path.exists(path):
          raise ValueError("Found JRE at " + path + "; but H2O requires the JDK to run.")

    else:
      raise ValueError("Cannot find Java. Please install the latest JDK from\n"
        +"http://www.oracle.com/technetwork/java/javase/downloads/index.html" )

  @staticmethod
  def _pwhich(e):
    """
    POSIX style which
    """
    ok = os.X_OK
    if e:
      if os.access(e, ok):
        return e
      for path in os.getenv('PATH').split(os.pathsep):
        full_path = os.path.join(path, e)
        if os.access(full_path, ok):
          return full_path
    return None

  @staticmethod
  def _tmp_file(type):
    if sys.platform == "windows":
      usr = re.sub("[^A-Za-z0-9]", "_", os.getenv("USERNMAME"))
    else:
      usr = re.sub("[^A-Za-z0-9]", "_", os.getenv("USER"))

    if type == "stdout":
      path = os.path.join(tempfile.mkdtemp(), "h2o_{}_started_from_python.out".format(usr))
      print "JVM stdout: " + path
      return path
    if type == "stderr":
      path = os.path.join(tempfile.mkdtemp(), "h2o_{}_started_from_python.err".format(usr))
      print "JVM stderr: " + path
      return path
    if type == "pid":
      return os.path.join(tempfile.mkdtemp(), "h2o_{}_started_from_python.pid".format(usr))

    raise ValueError("Unkown type in H2OConnection._tmp_file call: " + type)

  @staticmethod
  def get_session_id():
      return H2OConnection.get_json(url_suffix="InitID")["session_key"]

  @staticmethod
  def rest_version(): return __H2OCONN__._rest_version

  @staticmethod
  def session_id(): return __H2OCONN__._session_id

  @staticmethod
  def port(): return __H2OCONN__._port

  @staticmethod
  def ip(): return __H2OCONN__._ip

  @staticmethod
  def current_connection(): return __H2OCONN__

  @staticmethod
  def check_conn():
    if not __H2OCONN__:
      raise EnvironmentError("No active connection to an H2O cluster.  Try calling `h2o.init()`")
    return __H2OCONN__

  """
  Below is the REST implementation layer:
      _attempt_rest -- GET, POST, DELETE

      _do_raw_rest

      get
      post
      get_json
      post_json

  All methods are static and rely on an active __H2OCONN__ object.
  """

  @staticmethod
  def get(url_suffix, **kwargs):
    if __H2OCONN__ is None:
      raise ValueError("No h2o connection. Did you run `h2o.init()` ?")
    return __H2OCONN__._do_raw_rest(url_suffix, "GET", None, **kwargs)

  @staticmethod
  def post(url_suffix, file_upload_info=None, **kwargs):
    if __H2OCONN__ is None:
      raise ValueError("No h2o connection. Did you run `h2o.init()` ?")
    return __H2OCONN__._do_raw_rest(url_suffix, "POST", file_upload_info, **kwargs)

  @staticmethod
  def delete(url_suffix, **kwargs):
    if __H2OCONN__ is None:
      raise ValueError("No h2o connection. Did you run `h2o.init()` ?")
    return __H2OCONN__._do_raw_rest(url_suffix, "DELETE", None, **kwargs)

  @staticmethod
  def get_json(url_suffix, **kwargs):
    if __H2OCONN__ is None:
      raise ValueError("No h2o connection. Did you run `h2o.init()` ?")
    return __H2OCONN__._rest_json(url_suffix, "GET", None, **kwargs)

  @staticmethod
  def post_json(url_suffix, file_upload_info=None, **kwargs):
    if __H2OCONN__ is None:
      raise ValueError("No h2o connection. Did you run `h2o.init()` ?")
    return __H2OCONN__._rest_json(url_suffix, "POST", file_upload_info, **kwargs)

  def _rest_json(self, url_suffix, method, file_upload_info, **kwargs):
    raw_txt = self._do_raw_rest(url_suffix, method, file_upload_info, **kwargs)
    return self._process_tables(raw_txt.json())

  # Massage arguments into place, call _attempt_rest
  def _do_raw_rest(self, url_suffix, method, file_upload_info, **kwargs):
    if not url_suffix:
      raise ValueError("No url suffix supplied.")
    url = "http://{}:{}/{}/{}".format(self._ip,self._port,self._rest_version,url_suffix + ".json")

    query_string = ""
    for k,v in kwargs.iteritems():
      if isinstance(v, list):
        x = '['
        x += ','.join([str(l).encode("utf-8") for l in v])
        x += ']'
      else:
        x = str(v).encode("utf-8")
      query_string += k+"="+x+"&"
    query_string = query_string[:-1] # Remove trailing extra &

    post_body = ""
    if not file_upload_info:
      if method == "POST":
        post_body = query_string
      elif query_string != '':
        url = "{}?{}".format(url, query_string)
    else:
      if not method == "POST":
        raise ValueError("Received file upload info and expected method to be POST. Got: " + str(method))
      if query_string != '':
        url = "{}?{}".format(url, query_string)

    begin_time_seconds = time.time()
    http_result = self._attempt_rest(url, method, post_body, file_upload_info)
    end_time_seconds = time.time()
    elapsed_time_seconds = end_time_seconds - begin_time_seconds
    elapsed_time_millis = elapsed_time_seconds * 1000
    if not http_result.ok:
      raise EnvironmentError("h2o-py got an unexpected HTTP status code:\n {} {} (method = {}; url = {})"
                             .format(http_result.status_code,http_result.reason,method,url))

    # TODO: is.logging? -> write to logs
    # print "Time to perform REST call (millis): " + str(elapsed_time_millis)
    return http_result

  # Low level request call
  def _attempt_rest(self, url, method, post_body, file_upload_info):
    headers = {'User-Agent': 'H2O Python client/'+sys.version}
    try:
      if method == "GET":
        return requests.get(url, headers=headers)
      elif file_upload_info:
        files = {file_upload_info["file"] : open(file_upload_info["file"], "rb")}
        return requests.post(url, files=files, headers=headers)
      elif method == "POST":
        return requests.post(url, data=post_body, headers=headers)
      elif method == "DELETE":
        return requests.delete(url, headers=headers)
      else:
        raise ValueError("Unknown HTTP method " + method)

    except requests.ConnectionError as e:
      raise EnvironmentError("h2o-py encountered an unexpected HTTP error:\n {}".format(e.message))

    return http_result

  # TODO:
  # @staticmethod
  # def _process_matrices(x=None):
  #     if x:
  #         if isinstance(x, "dict"):
  #
  #     return x

  @staticmethod
  def _process_tables(x=None):
    if x:
      if isinstance(x, dict):

        has_meta = "__meta" in x
        has_schema_type = has_meta and "schema_type" in x["__meta"]

        have_table = has_schema_type and x["__meta"]["schema_type"] == "TwoDimTable"
        have_tableV1 = have_table and x["__meta"]["schema_name"] == "TwoDimTableV1"
        if have_tableV1:
          col_formats = [c["format"] for c in x["columns"]]
          table_header = x["name"]
          col_types = [c["type"] for c in x["columns"]]
          col_headers = [c["name"] for c in x["columns"]]
          row_headers = ["" for i in range(len(col_headers))]
          cell_values = x["data"]
          tbl = H2OTwoDimTable(row_headers, col_headers, col_types, table_header, cell_values, col_formats)
          x = tbl
        else:
          for k in x:
            x[k] = H2OConnection._process_tables(x[k])
      if isinstance(x, list):
        for it in range(len(x)):
          x[it] = H2OConnection._process_tables(x[it])
    return x


def get_human_readable_size(num):
  exp_str = [(0, 'B'), (10, 'KB'), (20, 'MB'), (30, 'GB'), (40, 'TB'), (50, 'PB'), ]
  i = 0
  rounded_val = 0
  while i + 1 < len(exp_str) and num >= (2 ** exp_str[i + 1][0]):
    i += 1
    rounded_val = round(float(num) / 2 ** exp_str[i][0], 2)
  return '%s %s' % (rounded_val, exp_str[i][1])


def get_human_readable_time(epochTimeMillis):
  days = epochTimeMillis/(24*60*60*1000.0)
  hours = (days-math.floor(days))*24
  minutes = (hours-math.floor(hours))*60
  seconds = (minutes-math.floor(minutes))*60
  milliseconds = (seconds-math.floor(seconds))*1000
  duration_vec = [int(math.floor(t)) for t in [days,hours,minutes,seconds,milliseconds]]
  names_duration_vec = ["days","hours","minutes","seconds","milliseconds"]

  duration_dict = dict(zip(names_duration_vec, duration_vec))

  readable_time = ""
  for name in names_duration_vec:
    if duration_dict[name] > 0:
      readable_time += str(duration_dict[name]) + " " + name + " "

  return readable_time

def is_int(possible_int):
  try:
    int(possible_int)
    return True
  except ValueError:
    return False

def as_int(the_int):
  if not is_int(the_int):
    raise ValueError("Not a valid int value: " + str(the_int))
  return int(the_int)

def _kill_jvm_fork():
  global __H2OCONN__
  if __H2OCONN__ is not None:
    if __H2OCONN__._child:
      __H2OCONN__._child.kill()
      print "Successfully stopped H2O JVM started by the h2o python module."

atexit.register(_kill_jvm_fork)
