#!/usr/bin/env python
 
import wsgiref.handlers
 
from google.appengine.api.labs import taskqueue
from google.appengine.ext import webapp
from google.appengine.api import users
from google.appengine.ext.webapp import template
from google.appengine.ext import db
from google.appengine.api import urlfetch
from google.appengine.api import mail
from google.appengine.ext.webapp.util import login_required
from datetime import datetime, timedelta
import urllib, hashlib, time, random
from django.utils import simplejson

GREETINGS = ['hello', 'hi', 'ahoy', 'welcome', 'greetings', 'howdy']

PBWORKS_TOKEN = None
def get_token(refresh=False):
	global PBWORKS_TOKEN
	if refresh or not PBWORKS_TOKEN:
		response = urlfetch.fetch('http://dojo.pbworks.com/api_v2/op/Login/email/appenginebot%40hackerdojo.com/password/botbotbot/_type/jsontext').content
		PBWORKS_TOKEN = parse_json(response)['token']
	return PBWORKS_TOKEN

def parse_json(data):
	return simplejson.loads(data.replace('/*-secure-','').replace('*/', ''))

def broadcast(**message):
	urlfetch.fetch('http://live.readyinrealtime.com/hackerdojo-signin', method='POST', payload=urllib.urlencode(message))

class Signin(db.Model):
	email = db.StringProperty(required=True)
	hash = db.StringProperty()
	name = db.StringProperty()
	image_url = db.StringProperty()
	type = db.StringProperty(required=True)
	created = db.DateTimeProperty(auto_now_add=True)
	closed = db.DateTimeProperty()
	time_delta = db.IntegerProperty()
	active = db.BooleanProperty(default=True)

	@classmethod
	def get_active_staff(cls):
		return cls.all().filter('type IN', ['StaffKey', 'StaffNoKey']).filter('active =', True).order('-created')
	
	@classmethod
	def deactivate_staffer(cls, email):
		staffer = cls.get_active_staff().filter('email =', email).get()
		staffer.active = False
		staffer.closed = datetime.now()
		td = datetime.now()-staffer.created
		staffer.time_delta = (td.days*86400)+td.seconds
		staffer.put()
	
	def name_or_nick(self):
		return self.name or self.email.split('@')[0]

class MainHandler(webapp.RequestHandler):
	def get(self):
		self.response.out.write(template.render('templates/main.html', locals()))
	
	def post(self):
		email = self.request.get('email')
		if not '@' in email:
			email = '%s@hackerdojo.com' % email
		if email:
			hash=hashlib.md5(email).hexdigest()
			
			# Defaults
			image = 'http://0.gravatar.com/avatar/%s' % hash
			name = email.split('@')[0].replace('.', ' ')
			say = '%s, %s' % (random.choice(GREETINGS), name.split(' ')[0])
			text = "Welcome back to Hacker Dojo, %s!" % name.split(' ')[0]
			
			# If on staff
			if 'Staff' in self.request.get('type'):
				response = urlfetch.fetch('http://dojo.pbworks.com/api_v2/op/GetUserInfo/_type/jsontext/email/%s/token/%s' % (urllib.quote(email), get_token())).content
				if not 'appenginebot' in response:
					response = parse_json(response)
					image = response['image']
					name = response['name']
					say = "Staff member, %s" % name
					text = "Welcome back, %s. Remember to check out when you leave!" % name.split(' ')[0]	
			else:
				# TODO: contact signup app
				# if member
				#   say = "member" + name
				# else...
				
				# If new visitor
				s = Signin.all().filter('email =', email).get()
				if not s:
					say = "Welcome to Hacker Dojo!"
					text = "Congrats on your first visit, %s!" % name
			
			s = Signin(email=email, type=self.request.get('type'), image_url=image, name=name)
			s.put()
			broadcast(text=text, say=say)
		self.redirect('/')

class StaffHandler(webapp.RequestHandler):
	def get(self):
		staff = Signin.get_active_staff()
		self.response.out.write(template.render('templates/staff.html', locals()))
	
	def post(self):
		email = self.request.get('email')
		if email:
			Signin.deactivate_staffer(email)
		self.redirect('/staff')

class MiniStaffHandler(webapp.RequestHandler):
	def get(self):
		staff = Signin.get_active_staff()
		isopen = staff.count() > 0
		self.response.out.write(template.render('templates/ministaff.html', locals()))

class TokenHandler(webapp.RequestHandler):
	def get(self):
		get_token(True)
		self.response.out.write("ok")

class AppreciationEmailHandler(webapp.RequestHandler):
	def get(self):
		staff_members = db.GqlQuery("SELECT * FROM Signin WHERE created >= DATETIME(:start) AND type = 'StaffKey'",
			start=(datetime.now()-timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S"))
		content = """To Dojo Staff:\n\nThanks for helping run the dojo last week!  Our heros included:\n""" % locals()
		totals = {}
		emails = []
		for staff_member in staff_members:
			emails.append(staff_member.email)
			if staff_member.name 	 in totals.keys():
				totals[staff_member.name] = totals[staff_member.name]+staff_member.time_delta
			else:
				totals[staff_member.name] = staff_member.time_delta
		for total in totals.keys():
			if(totals[total] > 0):
				content = content + " - " + total + ": " + str((totals[total])/60L) + " minutes\n"
			else:
				pass
		content = content + """\nThanks,\nEveryone at the Dojo"""
		mail.send_mail(sender="Hacker Dojo <hax@hackerdojo.com>",
		              to=", ".join(emails),
		              subject="Hacker Dojo Staff Appreciation",
		              body=content)
		self.response.out.write(content)
		self.response.out.write("ok")

class OpenHandler(webapp.RequestHandler):
	def get(self):
		staff = Signin.get_active_staff()
		count = staff.count(1000)
		if count > 0:
			staff = [s.name_or_nick().split(' ')[0] for s in staff.fetch(1000)]
			if count > 1:
				last_staff = staff.pop()
				self.response.out.write("Hacker Dojo is currently open, staffed by %s and %s." % (', '.join(staff), last_staff))
			else:
				self.response.out.write("Hacker Dojo is currently open, staffed by our hero, %s." % staff[0])
		else:
			self.response.out.write("Hacker Dojo is unfortunately closed.")

class JSONHandler(webapp.RequestHandler):
	def get(self):
		staff = Signin.get_active_staff()
		
		def to_dict(staffer):
		    return dict(
		        name=staffer.name_or_nick(),
		        email=staffer.email,
		        image_url=staffer.image_url,
		        type=staffer.type,
		        created=staffer.created.strftime("%m-%d-%Y %H:%M:%S"),
		        refTime=datetime.now().strftime("%m-%d-%Y %H:%M:%S"),)
		        
		self.response.out.write(simplejson.dumps([to_dict(staffer) for staffer in staff]))

def main():
    application = webapp.WSGIApplication([
        ('/', MainHandler), 
		('/ministaff', MiniStaffHandler),
		('/staff', StaffHandler),
		('/open', OpenHandler),
		('/refreshtoken', TokenHandler),
		('/appreciationemail', AppreciationEmailHandler),
        ('/staffjson', JSONHandler),
        ], debug=True)
    wsgiref.handlers.CGIHandler().run(application)
 
if __name__ == '__main__':
    main()
 