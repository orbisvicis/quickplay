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
import signal
import socket
import ssl
import re

class localServer:
  def __init__(self,url,port,protocol=socket.SOCK_STREAM,connections=1):
    self.url = url
    self.port = port
    self.protocol = protocol
    self.connections = connections

  def serverException(self,msg):
    print type(msg)
    print msg.args
    print msg

  def serverCreate(self):
    serverSocket = None
    try:
      serverSocket = socket.socket(socket.AF_INET, self.protocol)
    except socket.error, msg:
      print "Error defining serverSocket, defaulting to type None"
      self.serverException(msg)
      serverSocket = None
    try:
      serverSocket.bind((self.url,self.port))
      serverSocket.listen(self.connections)
    except socket.error, msg:
      print "Error binding/connecting, closing socket and returning to type None"
      self.serverException(msg)
      serverSocket.close()
      serverSocket = None
    self.serverSocket = serverSocket

  def serverAccept(self):
    while 1:
      no_data = 0
      client_socket, client_address = self.serverSocket.accept()
      url_play = urllib2.urlopen(os.read(serverSend, 1024))
      client_socket.send('HTTP/1.0 200 OK\r\n')
      client_socket.send(url_play.info().__str__())
      print(url_play.info().__str__())
      client_socket.send('\r\n')
      while no_data <= 5:
        data = url_play.read(4096)
        if not data:
          no_data+=1
        try:
          client_socket.send(data)
        except socket.error, msg:
          print "Sending data failed, client probably closed connection"
	  self.serverException(msg)
	  client_socket.close()
	  no_data = 10
	time.sleep(0.005)
      client_socket.close()
      del client_socket
      del client_address
      del url_play

  def serverClose(self):
    self.serverSocket.close()

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
  
  def __init__(self, url, parent, initial_vol, prog_bar):
    threading.Thread.__init__(self)
    _IdleObject.__init__(self)
    self.url = url
    self.parent = parent
    self.initial_vol = str(int(round(initial_vol*100)))
    self.prog_bar = prog_bar
  
  def run(self):
	#create our control fifo, this is very important for proper functionality
    if not os.path.exists(os.path.expanduser("~/.qpf")):
      os.mkfifo(os.path.expanduser("~/.qpf"))
    os.write(clientReceive, self.url)
    mplayerProcess = subprocess.Popen(("mplayer","-nolirc", "-noconsolecontrols", "-nolirc", "-nojoystick","-input", "file=" + os.path.expanduser("~/.qpf"),"-cache","8192","http://127.0.0.1:20000"),stdin=subprocess.PIPE,stdout=subprocess.PIPE,universal_newlines=False)
    while mplayerProcess.poll() == None:
      output = None
      try:
        output = mplayerProcess.stdout.read(512)
      except:
        pass
      try:
        output = output.rsplit('\x1b[J\r',2)
        output = output[1]
        output = output.split()
        position = float(output[1])
        total = float(167)
      except:
        pass
      try:
        self.prog_bar.set_fraction(position/total)
	self.prog_bar.set_text(str(position) + " / " + str(total))
      except:
        pass
    mplayerProcess.wait()
    self.prog_bar.set_fraction(1)
    self.prog_bar.set_text(" ")
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
      fh = open(os.path.expanduser('~/.qp_cache'), 'r')
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
      fh = open(os.path.expanduser('~/.qp_cache'), 'w')
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
      fh = open(os.path.expanduser('~/.qp.save'), 'w')
      fh.write(pickle.dumps(save))
      fh.close()
    self.com.fetch_artists(self.login_done)

  def login_done(self, data):
    gtk.gdk.threads_enter()
    self.collectionStore.clear()
    for each in data:
      #print "None " + str(each[0]) + " False " + " 0 " + str(each[1]) + " None"
      self.collectionStore.append(None, (each[0], False, 0, each[1], None))
    gtk.gdk.threads_leave()
    del data

  # convert TreeModelFilter iters and models to TreeStore iterns and models here ?
  def cache_item(self, model, titer):
    child_titer = model.convert_iter_to_child_iter(titer)
    view = self.collectionView
    iID = model.get_value(titer, 0)
    iSeen = model.get_value(titer, 1)
    itype = model.get_value(titer, 2)
    if itype == 0 and not iSeen:
      model.get_model().set_value(child_titer,1,True)
      return self.com.fetch_albums(iID, self.ci_cb, (model.get_model(), child_titer, 1))
    if itype == 1 and not iSeen:
      model.get_model().set_value(child_titer,1,True)
      return self.com.fetch_songs(iID, self.ci_cb, (model.get_model(), child_titer, 2))
                  
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
    self.player = mPlayer(url, self, self.volScroll.get_value(), self.progB)
    self.player_sig = self.player.connect('completed', self.play_next)
    self.player.start()

  def play(self):
    return

  def play_pause(self, widget):
    if self.player:
      if self.player.isAlive():
        f = open(os.path.expanduser("~/.qpf"), 'w')
        f.write("pause\n")
        f.close()

  def stop_button(self, widget):
    self.stop(None)

  def stop(self, widget):
    if self.player:
      if self.player.isAlive():
        self.player.disconnect(self.player_sig)
        f = open(os.path.expanduser("~/.qpf"), 'w')
        f.write("quit\n")
        f.close()
        self.player.join()

  def prev(self, widget):
    self.stop(None)
    self.play_prev()

  def next(self, widget):
    self.stop(None)
    self.play_next(None)

  def play_prev(self):
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

  def volume_adjust(self, widget, adjustment):
    if self.player:
      if self.player.isAlive():
        vol_change = int(round(adjustment*100))
	if vol_change%4 == 0:
          f = open(os.path.expanduser("~/.qpf"), 'w')
	  print "volume " + str(vol_change) + "  1"
	  f.write("volume " + str(vol_change) + "  1\n")
	  f.close()

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

  def refilterTree(self, widget, treeModelFilter):
    treeModelFilter.refilter()

  def clearFilter(self, widget, treeModelFilter, searchE):
    searchE.set_text('')
    self.refilterTree(widget, treeModelFilter)

  def matchText(self, model, titer, searchE):
    data = searchE.get_text()
    title = model.get_value(titer, 3)
    type = model.get_value(titer, 2)
    #print str(model.get_value(titer, 0))+" "+str(model.get_value(titer, 1))+" "+str(model.get_value(titer, 2))+" "+str(model.get_value(titer, 3))+" "+str(model.get_value(titer, 4))
    if data == '' or title == '' or data == None or title == None or type != 0:
      return True
    else:
      data = data.split() 
      match = False
      for each in data:
        regex = re.compile('.*'+each+'.*', re.IGNORECASE)
	if regex.match(title):
          match = True
      #print str(match)+" "+title
      del data
      del title
      return match

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
    authBox.pack_start(self.servE, True, True, 2)

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

    self.collectionStore = gtk.TreeStore(gobject.TYPE_INT, gobject.TYPE_BOOLEAN, gobject.TYPE_INT, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT)
    self.collectionFilter = self.collectionStore.filter_new()

    filterBox = gtk.HBox()

    searchButton = gtk.Button(label="Search")
    searchButton.show()
    searchButton.connect('clicked', self.refilterTree, self.collectionFilter)
    filterBox.pack_start(searchButton, False, False, 2)

    self.searchE = gtk.Entry()
    self.searchE.show()
    self.searchE.connect('activate', self.refilterTree, self.collectionFilter)
    filterBox.pack_start(self.searchE, True, True, 2)

    clearSearchButton = gtk.Button(label="Clear")
    clearSearchButton.show()
    clearSearchButton.connect('clicked', self.clearFilter, self.collectionFilter, self.searchE)
    filterBox.pack_start(clearSearchButton, False, False, 2)

    filterBox.show()

    mainBox.pack_start(filterBox, False, False, 2)

    collectionBox = gtk.ScrolledWindow()
    collectionBox.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)

    self.collectionFilter.set_visible_func(self.matchText, self.searchE)
    self.collectionView = gtk.TreeView(self.collectionFilter)
    self.collectionView.set_search_column(3)
    
    collectionColumn = gtk.TreeViewColumn("Artist / Album / Song")
    self.collectionView.append_column(collectionColumn)
    cRender = gtk.CellRendererText()
    collectionColumn.pack_start(cRender, True)
    collectionColumn.add_attribute(cRender, 'text', 3)
    collectionColumn.set_sort_column_id(3)

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

    self.volScroll = gtk.VolumeButton()
    self.volScroll.set_value(100)
    self.volScroll.show()
    self.volScroll.connect('value-changed', self.volume_adjust)
    butBox.pack_start(self.volScroll, False, True, 50)
    
    butBox.show()

    mainBox.pack_start(butBox, False, False, 2)

    mainBox.show()
    self.window.add(mainBox)    

    try:
      fh = open(os.path.expanduser('~/.qp.save'), 'r')
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
  serverReceive, clientSend = os.pipe()
  serverSend, clientReceive = os.pipe()

  pid = os.fork()
  if pid == 0:
    my_localServer = localServer("127.0.0.1",20000)
    my_localServer.serverCreate()
    my_localServer.serverAccept()
  else:
    qp = quickPlayer()
    qp.run()
    # this will close the fork after the main window has been killed
    os.kill(pid,signal.SIGTERM)
