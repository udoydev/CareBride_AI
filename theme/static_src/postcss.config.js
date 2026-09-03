module.exports = {
  plugins: {
    "@tailwindcss/postcss": {
      content: ["./../../../templates/**/*.html"],
    },
    "postcss-simple-vars": {},
    "postcss-nested": {}
  },
}
