import $ from 'jquery';
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

const profileFormTemplate = data => Handlebars.compile(`

  <h2>{{profile.name}}</h2>
  <div class="configure-block__container">
    <div class="configure-block">
      <h4 class="configure-block__label">Browser</h4>
      <p class="configure-block__description">The browser to use within the analyzer</p>
      <div class="configure-block__control--wrapper caret">
        <select value="{{profile.browser}}" class="configure-block__control">
          {{#each meta.browsers}}<option value="{{keyVal this}}">{{propKey this}}</option>{{/each}}
        </select>
      </div>
    </div>
    <div class="configure-block">
      <h4 class="configure-block__label">Route</h4>
      <p class="configure-block__description">Type of network routing for the VM</p>
      <div class="configure-block__control--wrapper caret">
        <select value="{{profile.route}}" class="configure-block__control">
          {{#each meta.routes}}<option value="{{this}}">{{this}}</option>{{/each}}
        </select>
      </div>
      <p class="configure-block__description">Via:</p>
      <div class="configure-block__control--wrapper caret">
        <select value="{{profile.country}}" class="configure-block__control">
          {{#each meta.countries}}<option value="{{this}}">{{this}}</option>{{/each}}
        </select>
      </div>
    </div>
  </div>
  <div class="flex-v">
    <div class="configure-block free">
      <h4 class="configure-block__label">Tags</h4>
      <p class="configure-block__description">Select multiple tags for the analyzer</p>
      <input type="text" class="configure-block__control auto" placeholder="Type to filter tag names" />
    </div>
    <div class="multi-select">
      <ul>
        <li>
          <input type="checkbox" id="ms-1" />
          <label for="ms-1">Tag 1</label>
        </li>
        <li>
          <input type="checkbox" id="ms-2" />
          <label for="ms-2">Tag 2</label>
        </li>
        <li>
          <input type="checkbox" id="ms-3" />
          <label for="ms-3">Tag 3</label>
        </li>
      </ul>
    </div>
  </div>
  <footer>
    <button>Delete</button>
    <button>Save</button>
  </footer>

`)(data);

/*
  Load a profile
 */
function selectProfile(id, $view) {
  return new Promise((res,rej) => {
    api.call('get', id).then(profile => {
      let form = $view.find('[data-profiles-form]');
      let data = {
        profile,
        meta: {
          ...EKpageContent
        }
      };
      form.empty();
      form.append(profileFormTemplate(data));
      initForm(data, form);
      res(form);
    }).catch(err => rej(err));
  })
}

/*
  Initializes a form
 */
function initForm() {
  console.log('init');
}

/*
  Initializes the profiles
 */
function initProfiles($view) {
  return new Promise(done => {

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

      done();
    });

  });
}

export { initProfiles };
