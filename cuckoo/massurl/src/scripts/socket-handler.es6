/*
  WebSocket library, credits to @Bun
 */

export default function stream(url, callbacks, interval, smart_backoff) {
  var had_initial_connection = false;

  var call = function(k, a, msg) {
    if (callbacks[k]) {
      var args = msg !== undefined ? [msg, callbacks] : [callbacks];
      args.push.apply(args, a);
      return callbacks[k].apply(callbacks, args);
    }
  };

  var onopen = function() {
    console.log('ws: Established:', url);
    had_initial_connection = true;
    call('onopen', arguments);
  };

  var onclose = function() {
    console.warn('ws: Disconnected:', url);
    if (!had_initial_connection && smart_backoff) {
      setTimeout(connect, 30000);
    } else {
      setTimeout(connect, interval);
    }
    try {
      call('onclose', arguments);
    } finally {
      callbacks.ws = null;
    }
  };

  var onerror = function() {
    console.warn('ws: Error:', url, arguments);
    call('onerror', arguments);
  };

  var onmessage = function(e) {
    var msg = e.data;
    call('onmessage', arguments, msg);
  };

  var connect = function() {
    var ws;
    try {
      ws = callbacks.ws = new WebSocket(url);
      ws.binaryType = 'arraybuffer';
    } catch (e) {
      console.log('WebSocket error: ' + e);
      return;
    }

    ws.onopen = onopen;
    ws.onclose = onclose;
    ws.onerror = onerror;
    ws.onmessage = onmessage;
  };

  callbacks.send = function(msg) {
    try {
      if (callbacks.ws) {
        //console.log('ws: Send:', msg);
        callbacks.ws.send(msg);
      }
    } catch (e) {
      console.error('Failed to send:', e);
    }
  };

  callbacks.close = function() {
    try {
      if (callbacks.ws) {
        console.log('ws: Close');
        callbacks.ws.close();
      }
    } catch (e) {
      console.error('Close error: ' + e);
    }
  };

  connect();
  return callbacks;
};
