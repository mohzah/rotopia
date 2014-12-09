#!/usr/bin/python

import xmlrpclib
from types import *


class TestopiaXmlrpcError(Exception):
	def __init__(self, cmd, args, error):
		self.cmd = cmd
		self.args = args
		self.error = error

	def __str__(self):
		return "Error while executing cmd '%s' --> %s" \
		% ( str(self.cmd) + "(" + str(self.args) + ")", self.error)


class Driver():
	def __init__(self, rpcserver_url, username=None, password=None):
		self.server = xmlrpclib.ServerProxy(rpcserver_url, allow_none=True)
		
		if username:
			self.username = username
			self.password = password
		self.login()

	def login(self):
		args = {'login' : self.username,
				'password' : self.password,
				'remember' : 1
				}
		id = self.server.User.login(args)
		self.TOKEN = id['token']

	def command(self, cmd, args):
		if not 'Bugzilla_login' in args:
			try:
				args['token'] = self.TOKEN
			except AttributeError as e:
				e.args += ("error: You are not logged in to the server\n",)
				raise e
		try:
			# todo : eval? emmm, eval is not safe, must be replaced
			eval_str = "self.server." + cmd + "(" + str(args) + ")"
			return eval(eval_str)
		except xmlrpclib.Error, e:
			print 'Fault code:', e.faultCode
			print 'Message   :', e.faultString
			raise TestopiaXmlrpcError(cmd, args, e)

	def get_env_id_by_name(self, environment_name):
		'''Returns integer id of enviroment named 'environment_name'.'''

		res = self.command('Environment.list', {'name':environment_name})
		environment_id = res[0]['environment_id']
		self.__set_product_id(res[0]['product_id']) # todo is it right to get product id of build from env
		return environment_id

	def __set_product_id(self, id):
		self.product_id = id

	def get_build_id_by_name(self, build_name, prod=None):
		'''Returns integer id of build named 'build_name'.

		get_env_id_by_name must be called before (first), if product is not passed as an arg.

		Args:
			build_name (str): name of build
			product (str/int): product_id or Product name
		'''
		# Todo : using prod argument should be implemented
		args = {'name':build_name, 'product':self.product_id}
		res = self.command('Build.check_build', args)
		res = res['build_id']
		return res

	def set_build_and_environment(self, build, environment):
		'''Returns None. Sets build and environment IDs either by name or id.

		Args:
			build_id (int/str): 
			environment_id (int/str):
		'''
		if not isinstance(environment, int):
			environment = self.get_env_id_by_name(environment)
		if not isinstance(build, int):
			build = self.get_build_id_by_name(build)

		self.build_id = build
		self.environment_id = environment

	def caserun_update(self, run_id, case_id, values):
		'''Updates and returns the updated caserun object as a hash.

		set_build_and_environment method must had been called (once) before calling this method.

		http://landfill.bugzilla.org/testopia2/docs/html/api/Bugzilla/WebService/Testopia/TestCaseRun.html
		args passed differently to rpc than how explained in Testopia doc, i.e. all go in one dict and no seprate dic for values as doc implies

		Args:
			value (dict): Hash of keys matching TestCaseRun fields and the new values
		'''
		args = {
		'run_id': run_id,
		'case_id': case_id,
		'build_id': self.build_id,
		'env_id': self.environment_id
		}
		args.update(values)
		return self.command('TestCaseRun.update', args)

	def caserun_running(self, run_id, case_id):
		'''This method starts a case run by changing its status to "RUNNING".

		This method is a simple call to case_run_update.
		set_build_and_environment method must had been called (once) before calling this method.

		Args:
			run_id (int): ID of the test run
			case_id (int): ID of the test case
		'''
		assert type(run_id) is IntType, "run_id passed to caserun_running is not an integer: %r" % run_id
		assert type(case_id) is IntType, "case_id passed to caserun_running is not an integer: %r" % case_id
		return self.caserun_update(run_id, case_id, {'status':'RUNNING'})

	def caserun_failed(self, run_id, case_id):
		'''changing case-run status to "FAILED".'''
		return self.caserun_update(run_id, case_id, {'status':'FAILED'})

	def caserun_passed(self, run_id, case_id):
		return self.caserun_update(run_id, case_id, {'status':'PASSED'})

	def caserun_set_notes(self, run_id, case_id, notes):
		'''
		Args:
			notes (str):
		'''
		return self.caserun_update(run_id, case_id, {'notes':notes})

	def create_run(self, plan_id, build, manager, summary):
		'''Creates a new Test Run. Returns created Run.

		set environment should have been called before this method
		This method authenticates by passing username and password directly.
		Using token is not possible due to a bug in one of bugzilla modules.
		Using cookies is also not possible as it is not supported anymore from buzilla 4.4
		'''
		args = {'plan_id': plan_id,
				'environment': self.environment_id,
				'build': build,
				'manager': manager,
				'summary': summary,
				}
		self.add_credentials(args)

		return self.command('TestRun.create', args)

	def get_test_plan(self, run_id):
		'''Get the plan_id that this run is associated with.
		'''
		args = {'run_id': run_id}
		return self.command('TestRun.list', args)[0]['plan_id']

	def get_plan_id(self, plan_text):
		args = {'plan_text' : plan_text}
		return self.command('TestPlan.list', args)[0]['plan_id']

	def create_plan(self, name, type='Integration', product_version='unspecified'):
		product = self.product_id
		args = {'name':name,
				'product':product,
				'type':type,
				'default_product_version':product_version
				}
		self.add_credentials(args)

		plan = self.command('TestPlan.create', args)
		return plan

	def create_case(self, priority, summary, plans, tester):
		# todo: making category, status, ... variable
		args = {'status': 'CONFIRMED',
				'category': 1,
				'priority': priority,
				'summary': summary,
				'plans': plans,
				'default_tester': tester,
				}
		self.add_credentials(args)
		return self.command('TestCase.create', args)

	def add_to_run(self, case_id, run_id):
		args = {'case_ids': case_id,
				'run_ids': run_id
				}
		return self.command('TestCase.add_to_run', args)

	def add_credentials(self, args):
		args['Bugzilla_login'] = self.username
		args['Bugzilla_password'] = self.password

	def update_case_action_result(self, case_id, action, result):
		args = {'case_id': case_id,
				'action': action,
				'effect': result,
				'setup':' ',
				'breakdown':' '
				}
		return self.command('TestCase.store_text', args)

def test_local():
	username = 'mohzah'
	password = ''

	TESTOPIAIP = 'http://127.0.0.1/bugzilla/xmlrpc.cgi'
	drv = Driver(rpcserver_url=TESTOPIAIP, username=username, password=password)

	drv.set_build_and_environment('build1', 'envio1')


def test_with_odl_server():
	username = ''
	password = ''

	rpc_address = 'https://bugs.opendaylight.org/xmlrpc.cgi'

	BUILD = 'controller base'	# ${BUNDLEVERSION}-${BUILDNUMBER}	Testopia Build (required for reporting)
	TEST_ENV = 'controller base'

	drv = Driver(rpcserver_url=rpc_address, username=username, password=password)
	
	t = drv.command('TestCase.get', {'id':'23'} )
	print t['case_id'], t['summary'], '\n\n'

	t = drv.get_env_id_by_name(TEST_ENV)
	print t, '\n\n'

	drv.set_build_and_environment(BUILD, TEST_ENV)


if __name__ == '__main__':
	test_local()
	#test_with_odl_server()
