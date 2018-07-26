import moment from 'moment';

const helpers = {
  // helper that parses 'alert level' to 'alert type'
  "alert-level": function() {
    return function(text, render) {
      let res, level = parseInt(render(text).trim(" "));
      switch(level) {
        case 1:
          res = "info";
          break;
        case 2:
          res = "warning";
          break;
        case 3:
          res = "danger";
          break;
        default:
          res = ""
      }
      return res;
    }
  },
  // helper that parses 'alert-level' to icon string
  "alert-icon": function() {
    return function(text, render) {
      let res, level = parseInt(render(text).trim(" "));
      switch(level) {
        case 1:
          res = "<i class='fal fa-lightbulb'></i>";
          break;
        case 2:
          res = "<i class='fal fa-exclamation-circle'></i>";
          break;
        case 3:
          res = "<i class='fal fa-skull'></i>";
          break;
        default:
          res = "<i class='fal fa-comment'></i>";
      }
      return res;
    }
  },
  // helper that pretty-prints a date (with moment)
  "pretty-date": function() {
    return function(text, render) {
      let date = render(text).trim();
      return moment(new Date(date)).format('MM/DD/YYYY HH:mm:ss');
    }
  },
  // helper that determines the route in app
  "active-link": function() {
    return function(text, render) {
      let res;
      return "class='active'";
    }
  }
}

export { helpers };
