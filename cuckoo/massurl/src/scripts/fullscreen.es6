/*

  Description:

  A utility class that shims the default native Fullscreen API implementations
  in JavaScript (for the browser). Does nothing if FullScreen is not available
  due to browser support / client browser configuration.

  Usage:

  Fullscreen.active()
    - returns if fullscreen is activated right now

  Fullscreen.enabled()
    - returns if the user enabled fullscreen

  Fullscreen.open([HTMLElement element])
    - opens [element] in fullscreen, (activate fullscreen on the element in html: <[tag] allowfullscreen />)

  Fullscreen.close()
    - closes the current fullscreen mode state

  Fullscreen.onChange([Function handler])
    - passes a handler to the fullscreen event listener

 */

export default class Fullscreen {

  // full screen active?
  static active() {
    if(document.fullscreen) {
      return document.fullscreen;
    } else if(document.webkitIsFullScreen) {
      return document.webkitIsFullScreen;
    } else if(document.mozIsFullScreen) {
      return document.mozIsFullScreen;
    } else if(document.msIsFullScreen) {
      return document.msIsFullScreen;
    } else {
      // ...
      return false;
    }
  }

  // retrieve availability (user config etc)
  static enabled() {
    if(document.fullscreenEnabled) {
      return document.fullscreenEnabled;
    } else if(document.webkitFullscreenEnabled) {
      return document.webkitFullscreenEnabled;
    } else if (document.mozFullscreenEnabled) {
      return document.mozFullscreenEnabled;
    } else {
      // ...
      return false;
    }
  }

  // open element in fullscreen mode
  static open(element) {
    if(Fullscreen.enabled()) {
      if(element.requestFullscreen) {
        element.requestFullscreen();
      } else if(element.webkitRequestFullscreen) {
        element.webkitRequestFullscreen();
      } else if (element.mozRequestFullscreen) {
        element.mozRequestFullscreen();
      } else if (element.msRequestFullscreen) {
        element.msRequestFullscreen();
      } else {
        console.log('Oh noes! you cannot go in fullscreen due to your browser.');
        return false;
      }
    } else {
      console.log('You did not enable fullscreen in your browser config. you cannot use this feature.');
      return false;
    }
  }

  // closes full screen mode
  static close() {
    if(document.exitFullscreen) {
      document.exitFullscreen();
    } else if(document.webkitExitFullscreen) {
      document.webkitExitFullscreen();
    } else if(document.mozExitFullscreen) {
      document.mozExitFullscreen();
    } else if(document.msExitFullscreen) {
      document.msExitFullscreen();
    } else {
      // the message has already been given in the request handler
      return false;
    }
  }

  // attach a handler to the fullscreen event shortcut
  onChange(handler = function(){}) {
    document.addEventListener('fullscreenchange', handler, false);
    document.addEventListener('webkitfullscreenchange', handler, false);
    document.addEventListener('mozfullscreenchange', handler, false)
    document.addEventListener('msfullscreenchange', handler, false);
  }

}
