import $ from 'jquery';
import EventEmitter  from './event-emitter';

export default class Paginator extends EventEmitter {

  constructor(props={}) {

    super();

    this.props = {
      url: null,
      limit: 0,
      offset: 0,
      autoIncrement: true,
      ...props
    }

    this.events = {
      request: [],
      payload: [],
      error: []
    }

  }

  // makes a request
  request() {
    let { url, limit, offset } = this.props;
    return new Promise((resolve, reject) => {
      $.get(
        this.url,
        response => {
          resolve(response);
        },
        error => {
          reject(error);
          this.emit('error', error);
        }, "json"
      );
    });
  }

  next() {
    let { offset, limit } = this.props;
    this.request().then(response => {
      this.emit('payload', { offset, response });
      if(this.props.autoIncrement)
        this.increment();
    }).catch(err => this.emit('error', err));
  }

  increment() { this.props.offset += 1; }

  get limit()   { return this.props.limit; }
  get offset()  { return this.props.offset; }
  get url()     { return `${this.props.url}?offset=${this.offset}&limit=${this.limit}`; }

  set offset(v) { this.props.offset = v; }

}
