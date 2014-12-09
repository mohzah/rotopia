
from driver import Driver
# from robot.output import LOGGER
import logging, time, sys
from ConfigParser import SafeConfigParser
# log_path = '/home/m/repo/db/created_suites.log'
# logging.basicConfig(filename=log_path, format='%(message)s\n', level=logging.DEBUG)

def get_plan_name(path):
	'''Returns directory name of the suite.

	based on the path of test suite returns the top level directory name to be used as plan name

	Args:
		path (string): absolute path of the suite
	'''
	idx = path.find(HIERARCHY_PREFIX) # HIERARCHY_PREFIX is read from config file
	path = path[idx+len(HIERARCHY_PREFIX):]
	plan_name = path[:path.find('/')]
	return plan_name

def read_config(server_name, https=False):
	'''
	different server names can be used for naming different sections in config file. hence,
	config file can contian different settings for different servers.

	Args:
		server_name (str): specifies which server url and credentials to be used
		https (bool): if true, uses url started with "https" in the config file, named "urls"
	'''
	parser = SafeConfigParser()
	parser.read('config.ini')
	url = 'url'
	if https:
		url = 'urls'
	settings = {}
	settings['username'] = parser.get(server_name, 'username')
	settings['password'] = parser.get(server_name, 'password')
	settings['url'] = parser.get(server_name, url)
	settings['database'] = parser.get('database', 'dbpath')
	settings['prefix'] = parser.get(server_name, 'HIERARCHY_PREFIX')
	global HIERARCHY_PREFIX
	HIERARCHY_PREFIX = settings['prefix']
	return settings

class Listener:
	'''
	http://robotframework.org/robotframework/latest/RobotFrameworkUserGuide.html#using-listener-interface
	'''

	ROBOT_LISTENER_API_VERSION = 2 # Do Not Change This

	def __init__(self, build, environment):
		'''
		Parameters come from invoking command i.e. variables seprated by ":" in pybot command

		Args:
			build (str): build name
			environment (str): environment name
		'''
		settings = read_config('localbugz')
		username = settings['username']
		# login of the manager
		# todo: omit it, make driver api more consistent
		self.MANAGER = username

		testopia_url = settings['url']
		self.driver = Driver(testopia_url, username, settings['password'])
		self.build = build
		self.environment = environment
		self.driver.set_build_and_environment(build, environment)
		self.no_run_id = False

		self.conn = Connector(settings['database'])

	def start_suite(self, name, attrs):
		'''
		http://robotframework.org/robotframework/latest/RobotFrameworkUserGuide.html#listener-interface-method-signatures
		'''
		doc = attrs['doc']	# doc is <type 'unicode'>
		self.absolute_path = attrs['source']
		tests = attrs['tests']	# empty suits return empty list
		if tests:	# empty list -> False	any list other than empty list -> True
			if not self.conn.is_exported_suite(self.absolute_path):
				# This is the first time this suite is executed and,
				plan_name = get_plan_name(self.absolute_path)
				plan_id = None
				if self.conn.is_exported_plan(plan_name):
					# a plan is already created for the suites in this directory
					plan_id = self.conn.get_PlanID(plan_name)
				else:
					# no plan has been created earlier that this suite belong to
					# plans are not created for every new suite but for new suites
					# with different top level directory
					plan_id = self.driver.create_plan(plan_name)['plan_id']
					self.conn.insert_plan_as_exported(plan_name, plan_id)
				# For every new suite a Run will be created:
				run = self.driver.create_run(plan_id, str(self.build), self.MANAGER, summary=str(doc))
				self.run_id = run['run_id']
				self.conn.insert_as_exported(self.absolute_path, self.run_id)
			else:
				# This is not a new suite and a Run already exist for it
				self.run_id = self.conn.get_RunID(self.absolute_path)

	def start_test(self, name, attrs):#todo: update doc string
		'''case [Documentation] must start with "case_id;;"
		'''
		self.newCase = False
		caselongname = attrs['longname'] #todo: should change to 'id', should work in new version of robot
		
		if not self.conn.is_exported_case(caselongname, self.absolute_path):
			# This case is newly added to the test suite or is the first time executed
			self.newCase = True
			self.actions = []
			self.results = []
			try:
				summary = name + ' - ' + attrs['doc']
				plan = self.driver.get_test_plan(self.run_id)
				case = self.driver.create_case(priority='Normal', summary=summary, plans=plan,
				 tester=self.MANAGER)
				self.case_id = case['case_id']	#todo: should case_id be class variable or local is ok?
				self.driver.add_to_run(self.case_id, self.run_id)
				self.conn.insert_case_as_exported(caselongname, self.absolute_path, self.case_id)
			except:
				print "Unexpected error in new TestCase processing:", sys.exc_info()[0]
				raise
		else:
			self.case_id = self.conn.get_CaseID(caselongname, self.absolute_path)

		self.driver.caserun_running(self.run_id, self.case_id)

	def end_test(self, name, attrs):
		status = attrs['status']

		if status == 'PASS':
			self.driver.caserun_passed(self.run_id, self.case_id)
		elif status == 'FAIL':
			self.driver.caserun_failed(self.run_id, self.case_id)
		
		if self.newCase:
			# Steps and results for new Case will be collected in a list by using start_keyword method
			# list will be converted to a string with a html list format and inserted in Testopia
			def make_html_list(elements):
				'''
				converts a list of "<li>...</li>" strings (i.e. collected list) to
				a <ol><li>...</li>...</ol> string
				'''
				elements = ''.join(elements)
				return '<ol>%s</ol>' % elements

			action = make_html_list(self.actions)
			result = make_html_list(self.results)
			self.driver.update_case_action_result(self.case_id, action, result)
		# clean up
		self.case_id = None

	def end_suite(self, name, attrs):
		self.no_run_id = False
		status = attrs['status']
		message = attrs['message']
		self.run_id = None

	def start_keyword(self, name, attrs):
		if self.newCase:
			self.actions.append('<li>%s</li>' % name)
			self.results.append('<li>%s</li>' % (attrs['doc'] or "No doc for keyword"))

	def close(self):
		self.conn.close()



import sqlite3 as lite

class Connector():
	def __init__(self, dbAddress):
		self.con = lite.connect(dbAddress)
		self.cur = self.con.cursor()    

	def commit(self):
		try:
			self.con.commit()
		except lite.Error, e:
			if self.con:
				self.con.rollback()
			raise e

	def close(self):
		self.con.close()

	def has_result(self):
		row = self.cur.fetchone()
		if row:
			return True
		return False

	def is_exported_suite(self, suite_path):
		self.cur.execute("SELECT * FROM ExportedCases WHERE SuitePath=?", (suite_path,))
		return self.has_result()

	def get_RunID(self, suite_path):
		self.cur.execute("SELECT RunID FROM ExportedCases WHERE SuitePath=?", (suite_path,))
		row = self.cur.fetchone()
		return row[0]

	def get_CaseID(self, stringID, suite_path):
		self.cur.execute("SELECT CaseID FROM ExportedCases WHERE \
						SuitePath=? AND CaseStringID=?", (suite_path, stringID))
		row = self.cur.fetchone()
		return row[0]

	def insert_as_exported(self, suite_path, run_id):
		self.cur.execute("INSERT INTO ExportedCases (SuitePath, RunID, Timestamp) \
						VALUES (?, ?, ?)", (suite_path, run_id, time.ctime()))
		self.commit()

	def is_exported_case(self, caseID, suite_path):
		self.cur.execute("SELECT * FROM ExportedCases WHERE \
						SuitePath=? AND CaseStringID=?", (suite_path, caseID))
		return self.has_result()


	def insert_case_as_exported(self, caseLongName, suite_path, case_id):
		'''
		'''
		self.cur.execute("INSERT INTO ExportedCases (SuitePath, CaseStringID, CaseID, Timestamp) \
						VALUES (?, ?, ?, ?)", (suite_path, caseLongName, case_id, time.ctime()))
		self.commit()

	def is_exported_plan(self, plan_name):
		self.cur.execute("SELECT * FROM ExportedCases WHERE \
						PlanName=?", (plan_name,))
		return self.has_result()

	def insert_plan_as_exported(self, plan_name, plan_id):
		self.cur.execute("INSERT INTO ExportedCases (PlanName, PlanID, Timestamp) \
						VALUES (?, ?, ?)", (plan_name, plan_id, time.ctime()))
		self.commit()

	def get_PlanID(self, plan_name):
		self.cur.execute("SELECT PlanID FROM ExportedCases WHERE \
						PlanName=?", (plan_name,))
		row = self.cur.fetchone()
		return row[0]