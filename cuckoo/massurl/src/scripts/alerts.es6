import $ from 'jquery';
import Templates from './templates';

const baseUrl = `${window.location.origin}/alerts/list`;

function initAlerts() {

  const response = {
    alerts: [],
    html: '',
    jq: function() {
      return $(this.html);
    }
  };

  return new Promise((resolve, reject) => {
    $.get(baseUrl, alerts => {
      response.alerts = alerts || [];
      let html = '';
      alerts.forEach(alert => html += Templates.event(alert));
      response.html = html;
      resolve(response || {});
    }).fail(err => reject({err}));
  });
}

export {
  initAlerts
}
