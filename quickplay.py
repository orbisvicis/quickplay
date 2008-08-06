#!/usr/bin/env python

# Copyright (c) 2008 Kevin James Purdy <purdyk@onid.orst.edu>
#
# +------------------------------------------------------------------------+
# | This program is free software; you can redistribute it and/or          |
# | modify it under the terms of the GNU General Public License            |
# | as published by the Free Software Foundation; either version 2         |
# | of the License, or (at your option) any later version.                 |
# |                                                                        |
# | This program is distributed in the hope that it will be useful,        |
# | but WITHOUT ANY WARRANTY; without even the implied warranty of         |
# | MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the          |
# | GNU General Public License for more details.                           |
# |                                                                        |
# | You should have received a copy of the GNU General Public License      |
# | along with this program; if not, write to the Free Software            |
# | Foundation, Inc., 59 Temple Place - Suite 330,                         |
# | Boston, MA  02111-1307, USA.                                           |
# +------------------------------------------------------------------------+



import pygtk
pygtk.require('2.0')
import gtk
import gobject
import md5
import time
import urllib2
import xml.dom.minidom
import threading
import os
import subprocess
import pickle


class _IdleObject(gobject.GObject):
  def __init__(self):
    gobject.GObject.__init__(self)

  def emit(self, *args):
    gobject.idle_add(gobject.GObject.emit, self, *args)

#Threaded mplayer class.  Create it with a url to a media file, start it and it plays.
class mPlayer(threading.Thread, _IdleObject):
  __gsignals__ = {
    'completed' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, ())
    }
  
  def __init__(self, url, parent):
    threading.Thread.__init__(self)
    _IdleObject.__init__(self)
    self.url = url
    self.parent = parent
  
  def run(self):
	#create our control fifo, this is very important for proper functionality
    if not os.path.exists(".qpf"):
      os.mkfifo(".qpf")
    mplayerProcess = subprocess.Popen(("mplayer", "-nolirc", "-noconsolecontrols", "-nolirc", "-nojoystick", "-quiet", "-input", "file=.qpf", self.url))
    mplayerProcess.wait()
    self.emit("completed")

gobject.type_register(mPlayer)
    
#Authentication error class, for the Ampache Communicator
class AuthError(Exception):
    """Authentication Failure"""
    pass

class ThreadedFetcher(threading.Thread, _IdleObject):
  def __init__(self, url, doneCB, args, progressCB=None):
    threading.Thread.__init__(self)
    self.progress = progressCB
    self.done = doneCB
    self.url = url
    self.args = args

  def run(self):
    #Connect to the server and prepare to receive
    if self.progress:
      self.progress(None, "Requesting...")
    try:
      temp = urllib2.urlopen(self.url)
    except:
      raise AuthError("Error connecting to server")

    #If they don't send content-length, we don't bother with progress
    headers = temp.info()
    try:
      size = int(headers['Content-Length'])
    except:
      data = ""
      chunk = temp.read(1024)
      if self.progress:
        self.progress(None, "Fetching...")
      while chunk:
        data += chunk
        chunk = temp.read(1024)
      if self.progress:
        self.progress(1, "")
    else:
      total = 0
      data = ""
      if self.progress:
        self.progress(0, "Fetching...")
      while total < size:
        data = data + temp.read(1024)
        total += 1024
        if total > size:
          total = size
        if self.progress:
          self.progress(float(total)/size, "Fetching...")
    if self.progress:
      self.progress(1, " ")
    self.done(data, self.args)

gobject.type_register(ThreadedFetcher)

#main communication class. 
class AmpacheCommunicator:
  def __init__(self, progress = None):
    self.progress = progress

  #internal function for fetching data.
  def fetch(self, append, callback, args):
    fetcher = ThreadedFetcher("%s%s" % (self.url, append), callback, args, self.progress)
    fetcher.start()
    return fetcher

  #reauthenticate, should get called on fetch error
  def reauthenticate(self):
    timestamp = int(time.time())
    auth = self.fetch("?action=handshake&auth=%s&timestamp=%s" % (md5.md5(str(timestamp) + password).hexdigest(), timestamp))
    dom = xml.dom.minidom.parseString(auth)
    try:
      self.auth = dom.getElementsByTagName("auth")[0].childNodes[0].data
    except:
      raise AuthError("Bad server key")
    
  #authentication function, does not account for timeouts...
  def authenticate(self, u, password, user, callback):
    self.password = password
    self.url = u + "/server/xml.server.php"
    timestamp = int(time.time())
    if user != None:
      self.fetch("?action=handshake&auth=%s&timestamp=%s&user=%s&version=350001" % (md5.md5(str(timestamp) + password).hexdigest(), timestamp, user), self.auth_cb, callback)
    else:
      self.fetch("?action=handshake&auth=%s&timestamp=%s&version=350001" % (md5.md5(str(timestamp) + password).hexdigest(), timestamp), self.auth_cb, callback)
    return True

  def auth_cb(self, auth, args):
    dom = xml.dom.minidom.parseString(auth)
    try:
      self.auth = dom.getElementsByTagName("auth")[0].childNodes[0].data
    except:
      raise AuthError(dom.getElementsByTagName("error")[0].childNodes[0].data)
    try:
      self.update = dom.getElementsByTagName("update")[0].childNodes[0].data
      self.add = dom.getElementsByTagName("add")[0].childNodes[0].data
      self.artists_num = int(dom.getElementsByTagName("artists")[0].childNodes[0].data)
    except:
      print "Didn't get extra catalog info"
    #run the post_auth callback
    args()

  def fetch_artists(self, callback):
    try:
      fh = open('.qp_cache', 'r')
    except:
      print "No cache file found, will generate"
    else:
      pd = pickle.loads(fh.read())
      fh.close()
      if hasattr(self, 'update') and hasattr(self, 'add'):
        if pd['update'] == self.update and pd['add'] == self.add and pd['url'] == self.url:
          callback(pd['data'])
          return
    self.artist_ret = []
    if self.artists_num <= 5000:
      return self.fetch("?action=artists&auth=%s" % (self.auth), self.fa_cb_inc , (self.fa_cb_done, callback, None, None))
    else:
      urls = []
      for i in range(0,self.artists_num, 5000):
        urls.append("?action=artists&auth=%s&offset=%i" % (self.auth, i))
      urls.reverse()

      args = (urls[0], self.fa_cb_inc, (self.fa_cb_done, callback, None, None))
      for each in urls[1:]:
        args = (each, self.fa_cb_inc, (self.fetch, args[0], args[1], args[2]))

      return self.fetch(args[0],args[1],args[2])
        
  def fa_cb_inc(self, artists, args):
    dom = xml.dom.minidom.parseString(artists)
    for node in dom.getElementsByTagName("artist"):
      self.artist_ret.append((int(node.getAttribute("id")), node.childNodes[1].childNodes[0].data))
    args[0](args[1], args[2], args[3])

  def fa_cb_done(self, args, junk1, junk2):
    if hasattr(self, 'update') and hasattr(self, 'add'):
      fh = open('.qp_cache', 'w')
      fh.write(pickle.dumps({'add': self.add, 'update': self.update, 'url': self.url, 'data': self.artist_ret}))
      fh.close()
    args(self.artist_ret)

  def fetch_albums(self, artistID, callback, args):
    return self.fetch("?action=artist_albums&auth=%s&filter=%s" % (self.auth, artistID), self.fal_cb, (callback, args))

  def fal_cb(self, albums, args):
    dom = xml.dom.minidom.parseString(albums)
    ret = []
    for node in dom.getElementsByTagName("album"):
       ret.append((int(node.getAttribute("id")),
                       node.getElementsByTagName("name")[0].childNodes[0].data,
                       node.getElementsByTagName("artist")[0].childNodes[0].data,
                       node.getElementsByTagName("year")[0].childNodes[0].data,
                       node.getElementsByTagName("tracks")[0].childNodes[0].data,
                       node.getElementsByTagName("art")[0].childNodes[0].data))
    args[0](ret, args[1])
  
  def fetch_songs(self, albumID, callback, args):
    return self.fetch("?action=album_songs&auth=%s&filter=%s" % (self.auth, albumID), self.fs_cb, (callback, args))
    
  def fs_cb(self, tracks, args):
    dom = xml.dom.minidom.parseString(tracks)
    ret = []
    for node in dom.getElementsByTagName("song"):
      ret.append((int(node.getAttribute("id")),
            node.getElementsByTagName("title")[0].childNodes[0].data,
            node.getElementsByTagName("artist")[0].childNodes[0].data,
            node.getElementsByTagName("album")[0].childNodes[0].data,
#            node.getElementsByTagName("genre")[0].childNodes[0].data if node.getElementsByTagName("genre") else 0,
            0,
            node.getElementsByTagName("track")[0].childNodes[0].data,
            node.getElementsByTagName("time")[0].childNodes[0].data,
            node.getElementsByTagName("url")[0].childNodes[0].data))
    args[0](ret, args[1])

#Main GUI and logic
class quickPlayer:
  def delete_event(self, widget, event, data=None):
    return False

  def destroy(self, widget, data=None):
    if self.player:
      if self.player.isAlive():
        self.stop(None)
      
    gtk.main_quit()
    
  def login(self, widget, data=None):
    try:
      self.com.authenticate(self.servE.get_text(), self.passE.get_text(), self.userE.get_text(), self.login_cb)
    except:
      print "Authentication Error"
    
  def login_cb(self):
    if self.authCB.get_active():
      save = (self.servE.get_text(), self.passE.get_text(), self.userE.get_text())
      fh = open('.qp.save', 'w')
      fh.write(pickle.dumps(save))
      fh.close()
    self.com.fetch_artists(self.login_done)

  def login_done(self, data):
    gtk.gdk.threads_enter()
    self.collectionStore.clear()
    for each in data:
      self.collectionStore.append(None, (each[0], False, 0, each[1], None))
    gtk.gdk.threads_leave()
    del data

  def cache_item(self, model, titer):
    view = self.collectionView
    iID = model.get_value(titer, 0)
    iSeen = model.get_value(titer, 1)
    itype = model.get_value(titer, 2)
    if itype == 0 and not iSeen:
      model.set_value(titer,1,True)
      return self.com.fetch_albums(iID, self.ci_cb, (model, titer, 1))
    if itype == 1 and not iSeen:
      model.set_value(titer,1,True)
      return self.com.fetch_songs(iID, self.ci_cb, (model, titer, 2))
                  
  def ci_cb(self, data, args):
    model = args[0]
    titer = args[1]
    val = args[2]
    gtk.gdk.threads_enter()
    for each in data:
      model.append(titer, (each[0], False, val, each[1], each))
    self.collectionView.expand_row(model.get_path(titer), False)
    gtk.gdk.threads_leave()

  def do_selection(self, selection, data=None):
    (model, titer) = selection.get_selected()
    if titer == None:
      return True
    self.cache_item(model, titer)

  def do_activate(self, view, path, data=None):
    if self.player:
      if self.player.isAlive():
        self.stop(None)
      
    titer = view.get_model().get_iter(path)
    self.playLevel = view.get_model().get_value(titer,2)
    if self.playLevel == 2:
      self.playLevel = 1
    self.play_item(titer)

  def play_item(self, titer):
    model = self.collectionView.get_model()
    while model.get_value(titer, 2) < 2: #Parse down the tree to the songs
      thread = self.cache_item(model, titer) #we have to cache the item before we can determine if it has children
      if thread:
        while thread.isAlive():
          gtk.main_iteration(block=True)
        thread.join()
      titer = model.iter_children(titer)
      if titer:
        self.collectionView.expand_row(model.get_path(titer), False)

    self.collectionSelection.select_iter(titer)

    url = model.get_value(titer, 4)[7]
    self.player = mPlayer(url, self)
    self.player_sig = self.player.connect('completed', self.play_next)
    self.player.start()

  def play(self):
    return

  def play_pause(self, widget):
    if self.player:
      if self.player.isAlive():
        f = open(".qpf", 'w')
        f.write("pause\n")
        f.close()

  def stop_button(self, widget):
    self.stop(None)

  def stop(self, widget):
    if self.player:
      if self.player.isAlive():
        self.player.disconnect(self.player_sig)
        f = open(".qpf", 'w')
        f.write("quit\n");
        f.close()
        self.player.join()

  def prev(self, widget):
    self.play_prev()

  def next(self, widget):
    self.play_next(None)

  def play_prev(self):
    if self.player:
      if self.player.isAlive():
        self.stop(None)
        
    (model, titer) = self.collectionSelection.get_selected()
    if titer:
      path = model.get_path(titer)
      prev = None
      if path[2] > 0:
        prev = model.get_iter_from_string("%i:%i:%i" % (path[0], path[1], path[2] - 1))
      elif path[1] > 0:
        prev = model.get_iter_from_string("%i:%i:0" % (path[0], path[1] - 1))
      if prev:
        if model.get_value(prev, 2) > self.playLevel:
          self.play_item(prev)

  def play_next(self, widget):
    #Get rid of already playing instance
    if self.player:
      if self.player.isAlive():
        self.stop(None)
        #if not self.next_override:
    (model, titer) = self.collectionSelection.get_selected()
    if titer:
      next = model.iter_next(titer)
      if not next:
        parent = model.iter_parent(titer)
        if model.get_value(parent, 2) > self.playLevel:
          next = model.iter_next(parent)
      if next:
        if model.get_value(next, 2) > self.playLevel:
          self.play_item(next)

  def progress(self, val, txt = None):
    gtk.gdk.threads_enter()
    if val == None:
      if not self.ticking:
        self.ticking = True
        gobject.idle_add(self.tick)
    else:
      self.ticking = False
      self.progB.set_fraction(val)
    if txt != None:
      self.progB.set_text(txt)
    gtk.gdk.threads_leave()

  def tick(self):
    if self.ticking:
      self.progB.pulse()
      time.sleep(.05)
      return True
    return False


  def __init__(self):
    gtk.gdk.threads_init()

    self.ticking = False

    self.player = None

    self.com = AmpacheCommunicator(self.progress)

    self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
    self.window.connect("delete_event", self.delete_event)
    self.window.connect("destroy", self.destroy)
    self.window.set_title("Ampache Quick Player")
    self.window.resize(600,600)

    mainBox = gtk.VBox()

    authBox = gtk.HBox()

    servLabel = gtk.Label("Server:")
    servLabel.show()
    authBox.pack_start(servLabel, False, False, 2)

    self.servE = gtk.Entry()
    self.servE.show()
    authBox.pack_start(self.servE, True, True ,2)

    passL = gtk.Label("Key:")
    passL.show()
    authBox.pack_start(passL, False, False, 2)

    self.passE = gtk.Entry()
    self.passE.set_visibility(False)
    self.passE.show()
    authBox.pack_start(self.passE, True, True, 2)

    userL = gtk.Label("User:")
    userL.show()
    authBox.pack_start(userL, False, False, 2)

    self.userE = gtk.Entry()
    self.userE.show()
    authBox.pack_start(self.userE, True, True, 2)

    self.authCB = gtk.CheckButton("Save")
    self.authCB.set_active(True)
    self.authCB.show()
    authBox.pack_start(self.authCB, True, True, 2)

    goBut = gtk.Button("Login")
    goBut.show()
    goBut.connect("clicked", self.login)
    authBox.pack_start(goBut, False, False, 2)

    authBox.show()

    mainBox.pack_start(authBox, False, False, 2)

    collectionBox = gtk.ScrolledWindow()
    collectionBox.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)

    self.collectionStore = gtk.TreeStore(gobject.TYPE_INT, gobject.TYPE_BOOLEAN, gobject.TYPE_INT, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT)
    self.collectionView = gtk.TreeView(self.collectionStore)
    self.collectionView.set_search_column(3)
    
    collectionColumn = gtk.TreeViewColumn("Artist / Album / Song")
    self.collectionView.append_column(collectionColumn)
    cRender = gtk.CellRendererText()
    collectionColumn.pack_start(cRender, True)
    collectionColumn.add_attribute(cRender, 'text', 3)

    self.collectionView.connect("row-activated", self.do_activate)

    self.collectionSelection = self.collectionView.get_selection()

    self.collectionSelection.connect("changed", self.do_selection)

    self.collectionView.show()
    collectionBox.add(self.collectionView)

    collectionBox.show()
    mainBox.add(collectionBox)

    self.progB = gtk.ProgressBar()
    self.progB.set_fraction(1)
    self.progB.set_pulse_step(.01)
    self.progB.show()
    mainBox.pack_start(self.progB, False, False, 1)

    butBox = gtk.HBox()

    prev = gtk.Button(None, gtk.STOCK_MEDIA_PREVIOUS)
    prev.show()
    prev.get_children()[0].get_children()[0].get_children()[1].hide()
    prev.connect('clicked', self.prev)
    butBox.pack_start(prev, True, True, 0)

    playPause = gtk.Button(None, gtk.STOCK_MEDIA_PAUSE)
    playPause.show()
    playPause.get_children()[0].get_children()[0].get_children()[1].hide()
    playPause.connect('clicked', self.play_pause)
    butBox.pack_start(playPause, True, True, 0)

    stopBut = gtk.Button(None, gtk.STOCK_MEDIA_STOP)
    stopBut.show()
    stopBut.get_children()[0].get_children()[0].get_children()[1].hide()
    stopBut.connect('clicked', self.stop_button)
    butBox.pack_start(stopBut, True, True, 0)

    next = gtk.Button(None, gtk.STOCK_MEDIA_NEXT)
    next.show()
    next.get_children()[0].get_children()[0].get_children()[1].hide()
    next.connect('clicked', self.next)
    butBox.pack_start(next, True, True, 0)
    
    butBox.show()

    mainBox.pack_start(butBox, False, False, 2)

    mainBox.show()
    self.window.add(mainBox)    

    try:
      fh = open('.qp.save')
      save = pickle.loads(fh.read())
      fh.close()
    except:
      save = None

    if save:
      self.servE.set_text(save[0])
      self.passE.set_text(save[1])
      self.userE.set_text(save[2])

    self.window.show()

  def run(self):
    gtk.main()
    return

if __name__ == "__main__":
  qp = quickPlayer()
  qp.run()
