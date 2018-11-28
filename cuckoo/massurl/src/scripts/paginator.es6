import $ from 'jquery';

export default class Paginator {

  constructor(props={}) {

    this.props = {
      url: null,
      current: 0,
      limit: 0,
      offset: 0,
      ...props
    }

  }

  request() {

    let { url, current, limit, offset } = this.props;
    this.increment = 1;

    console.log(this.current);

    return new Promise((resolve, reject) => {
      // $.get(
      //   `${url}?offset=${offset}&limit=${limit}`,
      //   response => resolve(response),
      //   error => reject(error)
      // )
      this.increment = 1;
      console.log(this.current);
      resolve();
    });
  }

  get current() { return this.props.current; }
  get limit() { return this.props.limit; }
  get offset() { return this.props.offset; }

  set increment(n=1) { this.props.current += n; }
  set decrement(n=1) { this.props.current -= (this.current == 0 ? 0 : n); }

}
