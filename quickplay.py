#!/usr/bin/env python
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

#Threaded mplayer class.  Create it with a url to a media file, start it and it plays.
class mPlayer(threading.Thread):
  def __init__(self, url, parent):
    self.url = url
    self.parent = parent
    threading.Thread.__init__(self)
    pass
  
  def run(self):
	#create our control fifo, this is very important for proper functionality
    if not os.path.exists(".qpf"):
      os.mkfifo(".qpf")
    mplayerProcess = subprocess.Popen(("mplayer", "-nolirc", "-noconsolecontrols", "-nolirc", "-nojoystick", "-quiet", "-input", "file=.qpf", self.url))
    mplayerProcess.wait()
    self.parent.play_next()
    
#Authentication error class, for the Ampache Communicator
class AuthError(Exception):
    """Authentication Failure"""
    pass

#main communication class. 
class AmpacheCommunicator:
  def __init__(self):
    self.playing = False

  #internal function for fetching data.
  def fetch(self, append):
    try:
      data = urllib2.urlopen("%s%s" % (self.url, append)).read()
    except:
      raise AuthError("Error connecting to server")
    if data == None:
      self.reauthenticate()
      data = urllib2.urlopen("%s%s" % (self.url, append)).read()
      if data == None:
        raise AuthError("Unknown fetch error")
    return data

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
  def authenticate(self, u, password, user=None):
    self.password = password
    self.url = u + "/server/xml.server.php"
    timestamp = int(time.time())
    if user != None:
      auth = self.fetch("?action=handshake&auth=%s&timestamp=%s&user=%s" % (md5.md5(str(timestamp) + password).hexdigest(), timestamp, user))
    else:
      auth = self.fetch("?action=handshake&auth=%s&timestamp=%s" % (md5.md5(str(timestamp) + password).hexdigest(), timestamp))
    dom = xml.dom.minidom.parseString(auth)
    try:
      self.auth = dom.getElementsByTagName("auth")[0].childNodes[0].data
    except:
      raise AuthError("Bad server key")

  def fetch_artists(self):
    artists = self.fetch("?action=artists&auth=%s" % (self.auth))
    dom = xml.dom.minidom.parseString(artists)
    ret = []
    for node in dom.getElementsByTagName("artist"):
      ret.append((int(node.getAttribute("id")), node.childNodes[1].childNodes[0].data))
    return ret
  
  def fetch_albums(self, artistID):
    albums = self.fetch("?action=artist_albums&auth=%s&filter=%s" % (self.auth, artistID))
    dom = xml.dom.minidom.parseString(albums)
    ret = []
    for node in dom.getElementsByTagName("album"):
       ret.append((int(node.getAttribute("id")),
                       node.getElementsByTagName("name")[0].childNodes[0].data,
                       node.getElementsByTagName("artist")[0].childNodes[0].data,
                       node.getElementsByTagName("year")[0].childNodes[0].data,
                       node.getElementsByTagName("tracks")[0].childNodes[0].data,
                       node.getElementsByTagName("art")[0].childNodes[0].data))
    return ret
  
  def fetch_songs(self, albumID):
    tracks = self.fetch("?action=album_songs&auth=%s&filter=%s" % (self.auth, albumID))
    dom = xml.dom.minidom.parseString(tracks)
    ret = []
    for node in dom.getElementsByTagName("song"):
      ret.append((int(node.getAttribute("id")),
            node.getElementsByTagName("title")[0].childNodes[0].data,
            node.getElementsByTagName("artist")[0].childNodes[0].data,
            node.getElementsByTagName("album")[0].childNodes[0].data,
            node.getElementsByTagName("genre")[0].childNodes[0].data,
            node.getElementsByTagName("track")[0].childNodes[0].data,
            node.getElementsByTagName("time")[0].childNodes[0].data,
            node.getElementsByTagName("url")[0].childNodes[0].data))
    return ret

class quickPlayer(threading.Thread):
  def delete_event(self, widget, event, data=None):
    return False

  def destroy(self, widget, data=None):
    if self.playing:
      f = open(".qpf", 'w')
      f.write("quit\n")
      f.close()
      
    gtk.main_quit()
    
  def login(self, widget, data=None):
    try:
      self.com.authenticate(self.servE.get_text(), self.passE.get_text(), self.userE.get_text())
    except:
      print "Error authenticating"
      return
    if self.authCB.get_active():
      save = (self.servE.get_text(), self.passE.get_text(), self.userE.get_text())
      fh = open('.qp.save', 'w')
      fh.write(pickle.dumps(save))
      fh.close()
    self.collectionStore.clear()
    for each in self.com.fetch_artists():
      self.collectionStore.append(None, (each[0], False, 0, each[1], None))

  def do_selection(self, selection, data=None):
    (model, titer) = selection.get_selected()
    if titer == None:
      return
    view = selection.get_tree_view()
    iID = model.get_value(titer, 0)
    iSeen = model.get_value(titer, 1)
    itype = model.get_value(titer, 2)
    if itype == 0 and not iSeen:
      model.set_value(titer,1,True)
      for each in self.com.fetch_albums(iID):
        model.append(titer, (each[0], False, 1, each[1], each))
      view.expand_row(model.get_path(titer), False)
      
    if itype == 1 and not iSeen:
      model.set_value(titer,1,True)
      for each in self.com.fetch_songs(iID):
        model.append(titer, (each[0], False, 2, each[1], each))
      view.expand_row(model.get_path(titer), False)
                  
  def do_activate(self, view, path, data=None):
    if self.playing:
      f = open(".qpf", 'w')
      f.write("quit\n")
      f.close()
      self.next_override = True

    if view.get_model().get_value(view.get_model().get_iter(path), 2) == 2:
      url = view.get_model().get_value(view.get_model().get_iter(path), 4)[7]
      self.playing = True
      player = mPlayer(url, self)
      player.start()

  def play(self):
    return

  def play_pause(self, widget):
    if self.playing:
      f = open(".qpf", 'w')
      f.write("pause\n")
      f.close()

  def stop(self, widget):
    if self.playing:
      self.playing = False
      f = open(".qpf", 'w')
      f.write("quit\n");
      f.close()

  def next(self):
    return

  def play_next(self):
    if self.playing:
      if not self.next_override:
        (model, titer) = self.collectionSelection.get_selected()
        next = model.iter_next(titer)
        if next:
          if model.get_value(next, 2) == 2:
            self.collectionSelection.select_iter(next)
            player = mPlayer(model.get_value(next, 4)[7], self)
            player.start()
          else:
            self.playing = False
        else:
          self.playing = False
      else:
        self.next_override = False

  def __init__(self):
    gtk.gdk.threads_init()

    self.playing = False
    self.next_override = False
    
    threading.Thread.__init__(self)
    pass
    
    self.com = AmpacheCommunicator()

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

    butBox = gtk.HBox()

    playPause = gtk.Button(None, gtk.STOCK_MEDIA_PAUSE)
    playPause.show()
    playPause.get_children()[0].get_children()[0].get_children()[1].hide()
    playPause.connect('clicked', self.play_pause)
    butBox.pack_start(playPause, True, True, 0)

    stopBut = gtk.Button(None, gtk.STOCK_MEDIA_STOP)
    stopBut.show()
    stopBut.get_children()[0].get_children()[0].get_children()[1].hide()
    stopBut.connect('clicked', self.stop)
    butBox.pack_start(stopBut, True, True, 0)
    
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
  qp.start()