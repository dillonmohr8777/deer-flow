const js = require("@eslint/js");

module.exports = [
  { ignores: ["node_modules/**", ".build/**", "out/**"] },
  js.configs.recommended,
  {
    files: ["**/*.cjs"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "commonjs",
      globals: {
        __dirname: "readonly",
        Buffer: "readonly",
        process: "readonly",
        URL: "readonly",
        URLSearchParams: "readonly",
        setImmediate: "readonly",
        setTimeout: "readonly",
      },
    },
    rules: {
      "no-unused-vars": ["error", { argsIgnorePattern: "^_", caughtErrors: "none" }],
    },
  },
];
