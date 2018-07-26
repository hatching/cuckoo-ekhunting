const SETTINGS = {

  /* =============
    BABEL CONFIG
  ============= */

  babel: {
    path: 'frontend/scripts',
    file: 'index.es6',
    output: '/build/main.js',
    browserify: {
      debug: true
    },
    babel: {
      "plugins": [
        "transform-custom-element-classes",
        "transform-es2015-classes"
      ],
      "presets": ["env"],
      "extensions": [".es6"],
      "sourceMaps": true
    },
    get inputPath() { return `${this.path}/${this.file}`; },
    get outputPath() { return util.prettyPath(this.output); }
  },

  /* =============
    SASS CONFIG
  ============= */
  sass: {
    path: './src/styles',
    file: 'main.scss',
    output: './build/css/styles.css',
    watchExtra: [
      './layout.yml'
    ],
    sass: {
      sourceMap: true,
      sourceMapContents: true,
      includePaths: [
        util.dep('bourbon/core'),
        util.dep('dropzone/src')
      ]
    }

  }

}

export default SETTINGS;
