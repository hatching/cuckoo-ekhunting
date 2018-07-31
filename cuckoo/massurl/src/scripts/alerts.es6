import $ from 'jquery';
import Templates from './templates';
import stream from './socket-handler';
import sound from './sounds';

const baseUrl = `${window.location.origin}/alerts/list`;
const socketBase = `ws://${window.location.host}/alerts`;
const urls = {
  alerts: (limit, offset) => `${baseUrl}?limit=${limit}&offset=${offset}`
}
let currentLimit = 20;
let currentOffset = 0;

// shifts background based on current state (on/off/toggle)
// swapBackground(null) => toggles
// swapBackground(true/false) => sets .fill-red class based on bool
// => this is for demonstrational purposes. Click the logo to trigger
function alertMode(toggle = null) {
  if(toggle === null) {
    if($("#app-background").hasClass('fill-red')) {
      $("#app-background").removeClass('fill-red');
    } else {
      $("#app-background").addClass('fill-red');
      sound('boop');
    }
  } else {
    $("#app-background").toggleClass('fill-red', toggle);
  }
}

// demonstrative function
function loopSocket() {
  setInterval(() => {
    let notify = [true,false][Math.floor(Math.random() * 2)];
    let lvl = [1,2,3][Math.floor(Math.random() * 3)];
    $.get(`${window.location.origin}/genalert?level=${lvl}&notify=${notify}`, response => {
      console.log(`generated alert [level: ${lvl}] [notify: ${notify}]`);
    });
  }, 10000);
}

function connectSocket(cb) {
  return new Promise((resolve, reject) => {
    let str = stream(socketBase, {
      onmessage: r => cb ? cb(JSON.parse(r)) : null,
      onerror: () => reject('Websocket returned an error')
    });
    resolve(str);
  });
}

// toggle-expand the info-row in the table
function expandInfoRow(e) {
  e.preventDefault();
  let row = $(e.currentTarget);
  row.parents('tbody').find('tr.expanded').not(row).removeClass('expanded');
  row.toggleClass('expanded');
}

function addAlert(alert, $table, method='prepend') {

  // pre-reset the alert mode
  alertMode(false);

  // create table entry
  let el = $(Templates.event(alert));
  $table.find('tbody')[method](el);
  el.on('click', expandInfoRow);

  // populate alert in top-level
  $("#top-level-alert").addClass('out');
  setTimeout(() => {
    let newContent = $(Templates.topEvent(alert));
    $("#top-level-alert .alert-outer").html(newContent);
    newContent.on('click', e => {
      $table.find(`tr[data-id=${alert.id || alert.task_id}]`).trigger('click');
    });
    setTimeout(() => {
      $("#top-level-alert").removeClass('out');
    }, 500);
  }, 300);

  if(alert.notify)
    alertMode();
}

function paginateNext() {
  return new Promise((resolve, reject) => {
    currentOffset += 1;
    console.log(`fetching page ${currentOffset}, retrieving ${currentLimit} more alerts.`);
    $.get(urls.alerts(currentLimit, currentOffset), response => resolve(response))
      .fail(err => reject(err));
  });
}

function initAlerts($table) {

  const response = {
    alerts: [],
    html: '',
    jq: function() {
      return $(this.html);
    }
  };

  $table.find('#paginate-next').on('click', e => {
    e.preventDefault();
    paginateNext().then(response => {
      if(response.length)
        response.forEach(alert => addAlert(alert, $table, 'append'));
    }).catch(err => console.log(err));
  });

  return new Promise((resolve, reject) => {

    $.get(baseUrl, alerts => {

      // constructs available alerts from API call
      response.alerts = alerts || [];
      alerts.forEach(alert => addAlert(alert, $table));
      if($table.find('tr.loading').length) {
        $table.find('tr.loading').remove();
      }

      connectSocket(alert => {
        addAlert(alert, $table);
      }).then(str => {
        response.stream = str;
        resolve(response || {});
      }).catch(e => reject(e));

    }).fail(err => reject({err}));

  });
}

export {
  initAlerts
}
