module.exports = {
  root: true,
  env: { browser: true, es2021: true },
  parser: "@typescript-eslint/parser",
  plugins: ["@typescript-eslint", "react-hooks"],
  extends: ["eslint:recommended", "plugin:@typescript-eslint/recommended", "plugin:react-hooks/recommended"],
  rules: { "@typescript-eslint/no-explicit-any": "off", "react-hooks/exhaustive-deps": "off", "no-empty": "off" },
  ignorePatterns: ["dist", "src/api/schema.d.ts"],
};
