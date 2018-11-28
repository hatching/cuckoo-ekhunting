/*
  An event mocking class
  - EventEmitter.events = { event: [], event2: [] ...etc }
  - EventEmitter.on('event', d => console.log('adds callbacks with data as d (d=whatever)'))
    ! You can use EventEmitter.on('event event') to subscribe 1 callback to multiple events. note space separator
  - EventEmitter.emit('event', (whatever)); // => runs callbacks from event[evt] added through ~.on(..^)
  - Special: EventEmitter.on('*') will be emitted on any 'emit'.
 */
export default class EventEmitter {
  constructor() {
    this.events={};
  }
  on(e, cb) {
    if(e.indexOf(' ') > -1) {
      // subscribe space-separated events iterative
      // (calls .on for each result on e splitted by spaces)
      e = e.split(' ').forEach(ev => this.on(ev, cb));
    } else {
      if(this.events[e]) {
        this.events[e].push(cb);
      } else {
        this.events[e] = [cb];
      }
    }
    return this;
  }
  emit(e,d={},any=false) {
    if(this.events[e]) {
      this.events[e].forEach(cb => {
        cb.call(this, d);
      });
    }
    if(!any) this.emit('*',e,true);
    return this;
  }
}
