
from driver import Driver
# from robot.output import LOGGER
import logging, time, sys
from ConfigParser import SafeConfigParser
# log_path = '/home/m/repo/db/created_suites.log'
# db_path = '/home/m/repo/db/testcases3.sqlite'
# logging.basicConfig(filename=log_path, format='%(message)s\n', level=logging.DEBUG)
# HIERARCHY_PREFIX = '/test/csit/suites/'
# HIERARCHY_PREFIX = '/home/m/repo/'


def get_plan_name(path):
	idx = path.find(HIERARCHY_PREFIX)
	path = path[idx+len(HIERARCHY_PREFIX):]
	plan_name = path[:path.find('/')]
	return plan_name

def read_config(server_name, https=False):
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

	ROBOT_LISTENER_API_VERSION = 2 # Do Not Change This

	# def __init__(self, protocol, testopia_url, build, environment):
	def __init__(self, build, environment):
		'''
		Args:
			protocol (str): http or https
			(because arg are seprated by ":" in issueing pybot command with listener in http://address http is one arg and //address is another)
		'''
		settings = read_config('localbugz')
		username = settings['username']
		# self.PLAN_ID = 1 # --> product id too # todo : where should it come from?
		self.MANAGER = username # login of the manager # todo: change to string


		# testopia_url = protocol + ':' + testopia_url # see docstring
		testopia_url = settings['url']
		self.driver = Driver(testopia_url, username, settings['password'])
		self.build = build
		self.environment = environment
		self.driver.set_build_and_environment(build, environment)
		self.no_run_id = False

		self.conn = Connector(settings['database'])

	def start_suite(self, name, attrs):
		'''suite Documentation must start with "${run_id};;".

		(can NOT use tags for instead of Documentation, since it is not passed in attrs)
		Documentation for test suite can be set in setting table. for more info:
		http://robotframework.googlecode.com/svn/tags/robotframework-2.1.3/doc/userguide/RobotFrameworkUserGuide.html#id168
		'''
		doc = attrs['doc']
		self.absolute_path = attrs['source']
		tests = attrs['tests']	# empty suits return empty list
		# logging.info(self.absolute_path) # todo: doens't work!?
		if len(tests) > 0:
			if not self.conn.is_exported_suite(self.absolute_path):
				plan_name = get_plan_name(self.absolute_path)
				plan_id = None
				if self.conn.is_exported_plan(plan_name):
					plan_id = self.conn.get_PlanID(plan_name)
				else:
					plan_id = self.driver.create_plan(plan_name)['plan_id']
					self.conn.insert_plan_as_exported(plan_name, plan_id)
				# self.driver.get_plan_id(plan_text)
				run = self.driver.create_run(plan_id, str(self.build), self.MANAGER, summary=str(doc))
				self.run_id = run['run_id']
				# logging.info(self.absolute_path)
				self.conn.insert_as_exported(self.absolute_path, self.run_id)
			else:
				self.run_id = self.conn.get_RunID(self.absolute_path)

	def start_test(self, name, attrs):#todo: update doc string
		'''case [Documentation] must start with "case_id;;"
		'''
		self.newCase = False
		caselongname = attrs['longname'] #todo: should change to id, should work in new version
		
		if not self.conn.is_exported_case(caselongname, self.absolute_path):
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
				print "Unexpected error:", sys.exc_info()[0]
				raise
		else:
			self.case_id = self.conn.get_CaseID(caselongname, self.absolute_path)

		self.driver.caserun_running(self.run_id, self.case_id)

	def end_test(self, name, attrs):
		status = attrs['status']

		if status == 'PASS':
			self.driver.caserun_passed(self.run_id, self.case_id)
		elif status == 'FAIL':
			#notes = attrs['message']
			self.driver.caserun_failed(self.run_id, self.case_id)
		
		if self.newCase:
			def listify(elements):
				'''converts a list of <li>...</li> elements to a <ol><li>...</li>...</ol> string
				'''
				elements = ''.join(elements)
				return '<ol>%s</ol>' % elements

			action = listify(self.actions)
			result = listify(self.results)
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