import $ from './jquery-with-plugins';
import Handlebars from 'handlebars';

/*
  Creates a promise mapping of the API calls
  usage:

  api.call(name, data, id)
  api.call('get', {}, 1)
 */
const api = {
  get: (d,id) => $.get(`/api/profile/${id}`),
  list: (d,id) => $.get(`/api/profile/list`),
  add: (d,id) => $.post(`/api/profile/add`, d),
  update: (d,id) => $.post(`/api/profile/update/${id}`, d),
  delete: (d,id) => $.post(`/api/profile/delete/${id}`),
  call: function(name=false, id=null, data={}) {
    return new Promise((res,rej) => {
      if(this.hasOwnProperty(name)) {
        this[name](data,id).done(response => {
          res(response);
        }).fail(err => rej(err));
      } else {
        rej(`${name} is not a registered API call`);
      }
    });
  }
};

/*
  Template of a single form
 */
Handlebars.registerHelper('propKey', (obj,opts) => Object.keys(obj)[0]);
Handlebars.registerHelper('keyVal', (obj,opts) => obj[Object.keys(obj)[0]]);
Handlebars.registerHelper('eq', (p,m,opts) => p == m ? opts.fn() : '');
Handlebars.registerHelper('eqo', (p,m,opts) => p == m[Object.keys(m)[0]] ? opts.fn() : '');
Handlebars.registerHelper('hasTag', (tag,tags,opts) => (tags.map(t=>t.id).indexOf(tag) !== -1) ? opts.fn() : '');

const profileFormTemplate = data => Handlebars.compile(`
  <h2>
    {{#if meta.new}}
      New profile
    {{else}}
      {{profile.name}}
    {{/if}}
  </h2>
  <div class="configure-block__container">
    {{#if meta.new}}
      <div class="configure-block">
        <h4 class="configure-block__label">Name:</h4>
        <p class="configure-block__description">Type a name for this profile.</p>
        <input type="text" class="configure-block__control" placeholder="Type a name" name="profile-name" />
      </div>
    {{/if}}
    <div class="configure-block">
      <h4 class="configure-block__label">Browser</h4>
      <p class="configure-block__description">The browser to use within the analyzer</p>
      <div class="configure-block__control--wrapper caret">
        <select class="configure-block__control" name="browser">
          {{#each meta.browsers}}
            <option value="{{keyVal this}}" {{#eqo ../profile.browser this}}selected{{/eqo}}>{{propKey this}}</option>
          {{/each}}
        </select>
      </div>
    </div>
    <div class="configure-block">
      <h4 class="configure-block__label">Route</h4>
      <p class="configure-block__description">Type of network routing for the VM</p>
      <div class="configure-block__control--wrapper caret">
        <select class="configure-block__control" name="route">
          {{#each meta.routes}}
            <option value="{{this}}" {{#eq this ../profile.route}}selected{{/eq}}>{{this}}</option>
          {{/each}}
        </select>
      </div>
      <div class="configure-block__control--wrapper caret inline" data-countries-vpn hidden>
        <p class="configure-block__description">Via:</p>
        <select value="{{profile.country}}" class="configure-block__control" name="country-vpn">
          <option value="">Automatic</option>
          {{#each meta.countries.vpn}}
            <option value="{{this}}" {{#eq ../profile.country this}}selected{{/eq}}>{{this}}</option>
          {{/each}}
        </select>
      </div>
      <div class="configure-block__control--wrapper caret inline" data-countries-socks5 hidden>
        <p class="configure-block__description">Via:</p>
        <select value="{{profile.country}}" class="configure-block__control" name="country-socks5">
          <option value="">Automatic</option>
          {{#each meta.countries.socks5}}
            <option value="{{this}}" {{#eq ../profile.country this}}selected{{/eq}}>{{this}}</option>
          {{/each}}
        </select>
      </div>
    </div>
  </div>
  <div class="flex-v">
    <div class="configure-block flex-h free">
      <div>
        <h4 class="configure-block__label">Tags</h4>
        <p class="configure-block__description">Select multiple tags for the analyzer</p>
      </div>
      <input type="text" class="configure-block__control overlap-control auto" placeholder="Type to filter tag names" name="filter-tags" />
    </div>
    <div class="multi-select scroll-vertical">
      <ul>
        {{#each meta.tags}}
          <li data-filter-value="{{name}}">
            <input type="checkbox" id="tag-{{id}}" name="tags" value="{{id}}" {{#hasTag id ../profile.tags}}checked{{/hasTag}} />
            <label for="tag-{{id}}">{{name}}</label>
          </li>
        {{/each}}
      </ul>
    </div>
  </div>
  <footer {{#if meta.new}}class="align-right"{{/if}}>
    {{#unless meta.new}}
      <button id="delete-profile">Delete</button>
    {{/unless}}
    <button id="save-profile">{{#if meta.new}}Create{{else}}Save{{/if}}</button>
  </footer>
`)(data);

/*
  Load a profile
 */
function selectProfile(id, $view) {

  // renders the form and calls initialization scripts
  let render = (profile, blank=false) => {
    let form = $view.find('[data-profiles-form]');
    let data = {
      profile: profile,
      meta: {
        new: blank,
        ...window.EKPageContent
      }
    };

    form.empty();
    form.append(profileFormTemplate(data));
    initForm(data, form);
    return form;
  }

  return new Promise((res,rej) => {
    if(id) {
      // load existing profile
      api.call('get', id).then(profile => {
        let form = render(profile, false);
        res(form);
      }).catch(err => rej(err));
    } else {
      // render a new profile
      let form = render({
        browser: "ie",
        country: "",
        name: "New profile",
        route: "internet",
        tags: []
      }, true);
      res(form);
    }
  })
}

/*
  Initializes a form
 */
function initForm(data, $form) {

  const inputs = {
    $name: $form.find('input[name="profile-name"]'),
    $browser: $form.find('select[name="browser"]'),
    $route: $form.find('select[name="route"]'),
    $countrySocks: $form.find('select[name="country-socks5"]'),
    $countryVPN: $form.find('select[name="country-vpn"]'),
    $tags: $form.find('input[name="tags"]'),
    $tagFilters: $form.find('input[name="filter-tags"]'),
    $save: $form.find('button#save-profile'),
    $delete: $form.find('button#delete-profile')
  }

  data.profile.tags = data.profile.tags.map(t=>t.id);

  // set country property
  let setCountry = e => data.profile.country = $(e.currentTarget).val();
  inputs.$countrySocks.on('change', setCountry);
  inputs.$countryVPN.on('change', setCountry);

  // detect browser selection values
  inputs.$browser.on('change', e => {
    data.profile.browser = $(e.currentTarget).val();
  }).trigger('change');

  // show/hide input mechanics for routes + countries
  inputs.$route.on('change', e => {
    let val = inputs.$route.val();
    data.profile.route = val;

    switch(val) {
      case 'vpn':
        inputs.$countrySocks.parent().attr('hidden', true);
        inputs.$countryVPN.parent().attr('hidden', false);
        inputs.$countryVPN.trigger('change');
      break;
      case 'socks5':
        inputs.$countrySocks.parent().attr('hidden', false);
        inputs.$countryVPN.parent().attr('hidden', true);
        inputs.$countrySocks.trigger('change');
      break;
      default:
        inputs.$countrySocks.parent().attr('hidden', true);
        inputs.$countryVPN.parent().attr('hidden', true);
        data.profile.country = "";
    }
  }).trigger('change');

  // set tags on change
  inputs.$tags.on('change', e => {
    let tags = [];
    data.profile.tags = inputs.$tags.filter(':checked').each(function() {
      tags.push(parseInt($(this).val()));
    });
    data.profile.tags = tags;
  });

  // bind save listeners (new=add,not new=update)
  inputs.$save.on('click', e => {

    data.profile.tags = data.profile.tags.join(',');

    if(data.meta.new) {
      // CREATE
      data.profile.name = inputs.$name.val();
      api.call('add', null, {
        name: data.profile.name,
        ...data.profile
      }).then(response => {
        let item = $(`
          <li>
            <a href="load:${response.profile_id}">${data.profile.name}</a>
          </li>
        `);
        $("[data-profiles-list]").append(item);
        item.find('a').on('click', evt => {
          evt.preventDefault();
          $(evt.currentTarget).parents('ul').find('.active').removeClass('active');
          $(evt.currentTarget).addClass('active');
          selectProfile($(evt.currentTarget).attr('href').split(':')[1], $("#profiles"));
        }).click();
        // reset string to array
        data.profile.tags = data.profile.tags.split(',').forEach(t=>parseInt(t));
      }).catch(err => console.log(err));
    } else {
      // UPDATE
      api.call('update', data.profile.id, {
        ...data.profile
      }).then(response => {
        // reset string to array
        data.profile.tags = data.profile.tags.split(',').forEach(t=>parseInt(t));
      }).catch(err => console.log(err));
    }

  });

  inputs.$delete.on('click', e => {
    api.call('delete', data.profile.id).then(response => {
      $("[data-profiles-list]").find('a.active').remove();
      $form.empty();
    });
  });

  inputs.$tagFilters.on('keyup', e => {
    let val = $(e.currentTarget).val();
    inputs.$tags.parents('ul').filterList(val);
  });

  if(data.meta.new)
    inputs.$name.focus();

}

/*
  Initializes the profiles
 */
function initProfiles($view) {

  return new Promise(done => {

    // generate list of existing profiles
    api.call('list').then(profileList => {
      let list = $view.find('[data-profiles-list]');
      if(profileList.length) {

        $.each(profileList, (i,profile) => list.append(`
          <li>
            <a href="load:${profile.id}">${profile.name}</a>
          </li>
        `));

        list.find('a').on('click', e => {
          e.preventDefault();
          let id = $(e.currentTarget).attr('href').split(':')[1];
          selectProfile(id, $view).then(() => {
            list.find('.active').removeClass('active');
            $(e.currentTarget).addClass('active');
          });
        });

        list.find('a').first().click();

      }
    });

    // new profile handler
    $view.find("#new-profile").on('click', e => {
      e.preventDefault();
      selectProfile(null, $view);
      $view.find('[data-profiles-list] .active').removeClass('active');
    });

    done();
  });
}

export { initProfiles };
