"""A simple guestbook app to test parts of NDB end-to-end."""

import cgi
import logging
import sys
import time

from google.appengine.api import users
from google.appengine.datastore import entity_pb
from google.appengine.ext import webapp
from google.appengine.ext.webapp import util

from core import datastore_query
from core import datastore_rpc
from core import monkey

import bpt
from ndb import context
from ndb import eventloop
from ndb import model
from ndb import tasks

HOME_PAGE = """
<script>
function focus() {
  textarea = document.getElementById('body');
  textarea.focus();
}
</script>
<body onload=focus()>
  Logged in as <a href="/account">%(email)s</a> |
  <a href="%(login)s">login</a> |
  <a href="%(logout)s">logout</a>

  <form method=POST action=/>
    <!-- TODO: XSRF protection -->
    <input type=text id=body name=body size=60>
    <input type=submit>
  </form>
</body>
"""

ACCOUNT_PAGE = """
<body>
  Logged in as <a href="/account">%(email)s</a> |
  <a href="%(logout)s">logout</a>

  <form method=POST action=/account>
    <!-- TODO: XSRF protection -->
    Email: %(email)s
    <input type=submit name=%(action)s value="%(action)s Account">
    <input type=submit name=delete value="Delete Account">
    <a href=/>back to home page</a>
  </form>
</body>
"""

class Account(model.Model):
  """A user."""

  email = model.StringProperty()
  userid = model.StringProperty()

class Message(model.Model):
  """A guestbook message."""

  body = model.StringProperty()
  when = model.IntegerProperty()
  userid = model.StringProperty()

def WaitForRpcs():
  eventloop.run()

@tasks.task
def AsyncGetAccountByUser(context, user, create=False):
  """Find an account."""
  assert isinstance(user, users.User), '%r is not a User' % user
  assert user.user_id() is not None, 'user_id is None'
  prop = entity_pb.Property()
  prop.set_name(Account.userid.name)
  prop.set_multiple(False)
  pval = prop.mutable_value()
  pval.set_stringvalue(user.user_id())
  pred = datastore_query.PropertyFilter('=', prop)
  query = datastore_query.Query(kind=Account.GetKind(),
                                filter_predicate=pred)
  options = datastore_query.QueryOptions(limit=1)

  def callback(entity):
    return entity  # TODO: This should be the default callback?
  fut1, fut2 = context.map_query(query, callback, options)
  res1, res2 = yield fut1, fut2
  assert len(res1) == res2
  if res1:
    account = res1[0]
    assert isinstance(account, Account)
    raise tasks.Return(account)

  if not create:
    return  # None

  account = Account(key=model.Key(flat=['Account', user.user_id()]),
                    email=user.email(),
                    userid=user.user_id())
  # Write to datastore asynchronously.
  context.put(account)  # Don't wait
  raise tasks.Return(account)

def GetAccountByUser(context, user, create=False):
  fut = AsyncGetAccountByUser(context, user, create)
  return fut.get_result()

class HomePage(webapp.RequestHandler):

  def get(self):
    self.ctx = context.Context()
    user = users.get_current_user()
    email = None
    if user is not None:
      email = user.email()
      # TODO: Use GetAccountByUser() for this too.
    values = {'email': email,
              'login': users.create_login_url('/'),
              'logout': users.create_logout_url('/'),
              }
    self.response.out.write(HOME_PAGE % values)
    order = datastore_query.PropertyOrder(
      'when',
      datastore_query.PropertyOrder.DESCENDING)
    query = datastore_query.Query(kind=Message.GetKind(), order=order)
    options = datastore_query.QueryOptions(batch_size=13, limit=50)
    fut1, fut2 = self.ctx.map_query(query, self._result_callback, options)
    futures = fut1.get_result()
    size = fut2.get_result()
    assert len(futures) == size
    results = [f.get_result() for f in futures]
    results.sort()
    for key, text in results:
      self.response.out.write(text)

  @tasks.task
  def _result_callback(self, result):
    # Task started for each query result.
    if result.userid is not None:
      key = model.Key(flat=['Account', result.userid])
      account = yield self.ctx.get(key)
      if account is None:
        author = 'Withdrawn'
      else:
        author = account.email
    else:
      author = 'Anonymous'
    raise tasks.Return((-result.when,
                        '%s / %s &mdash; %s<br>' %
                        (cgi.escape(author),
                         time.ctime(result.when),
                         cgi.escape(result.body))))

  def post(self):
    ctx = context.Context()
    body = self.request.get('body')
    if not body.strip():
      self.redirect('/')
      return
    user = users.get_current_user()
    logging.info('body=%.100r', body)
    body = body.rstrip()
    if body:
      msg = Message()
      msg.body = body
      msg.when = int(time.time())
      if user is not None:
        msg.userid = user.user_id()
      # Write to datastore asynchronously.
      rpc = model.conn.async_put(None, [msg])
      eventloop.queue_rpc(rpc, rpc.check_success)
      if user is not None:
        # Check that the account exists and create it if necessary.
        GetAccountByUser(ctx, user, create=True)
    self.redirect('/')
    WaitForRpcs()

class AccountPage(webapp.RequestHandler):

  def get(self):
    ctx = context.Context()
    user = users.get_current_user()
    if user is None:
      self.redirect(users.create_login_url('/account'))
      return
    email = user.email()
    account = GetAccountByUser(ctx, user)
    action = 'Create'
    if account is not None:
      action = 'Update'
    values = {'email': email,
              'action': action,
              'login': users.create_login_url('/account'),
              'logout': users.create_logout_url('/'),
              }
    self.response.out.write(ACCOUNT_PAGE % values)

  def post(self):
    ctx = context.Context()
    user = users.get_current_user()
    if user is None:
      self.redirect(users.create_login_url('/account'))
      return
    if self.request.get('delete'):
      account = GetAccountByUser(ctx, user)
      if account is not None:
        ctx.delete(account.key).check_success()
      self.redirect('/account')
      return
    account = GetAccountByUser(ctx, user, create=True)
    assert isinstance(account, Account), account
    WaitForRpcs()
    self.redirect('/account')

urls = [
  ('/', HomePage),
  ('/account', AccountPage),
  ]

app = webapp.WSGIApplication(urls)

def main():
  util.run_wsgi_app(app)

if __name__ == '__main__':
  main()
