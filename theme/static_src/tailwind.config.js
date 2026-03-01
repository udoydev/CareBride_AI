/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    '../../templates/**/*.{html,js}',
    '../../../templates/**/*.{html,js}',
    '../../../**/templates/**/*.{html,js}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Outfit', 'Hind Siliguri', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
      },
      colors: {
        teal: { 600: '#0f766e', 700: '#0b5f58' },
      },
    },
  },
  plugins: [
    require('daisyui'),
  ],
  daisyui: {
    themes: ["light", "dark", "cupcake"],
  },
}
/** @type {import('tailwindcss').Config} */
// module.exports = {
//   darkMode: 'class',
//   content: [
//     '../../templates/**/*.{html,js}',
//     '../../../templates/**/*.{html,js}',
//     '../../../**/templates/**/*.{html,js}',
//   ],
//   theme: {
//     extend: {
//       colors: {
//         teal: { 600: '#0f766e', 700: '#0b5f58' },
//       },
//     },
//   },
//   plugins: [],
// }
