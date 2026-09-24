import { describe, expect, test } from "@rstest/core";

import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import { parseCron } from "@/core/scheduled-tasks/cron";
import { RECIPES } from "@/core/scheduled-tasks/recipes";

describe("scheduled-task recipes", () => {
  test("every recipe has a title and description in both locales", () => {
    for (const recipe of RECIPES) {
      for (const locale of [enUS, zhCN]) {
        const labels = locale.scheduledTasks.recipes[recipe.titleKey];
        expect(labels.title.trim()).not.toBe("");
        expect(labels.desc.trim()).not.toBe("");
      }
    }
  });

  test("every schedule stays editable instead of falling to custom", () => {
    for (const recipe of RECIPES) {
      const { preset } = parseCron(recipe.schedule.schedule_spec.cron ?? "");
      expect(preset, recipe.id).not.toBe("custom");
    }
  });

  test("copy carries no em or en dashes", () => {
    for (const recipe of RECIPES) {
      const labels = enUS.scheduledTasks.recipes[recipe.titleKey];
      for (const text of [recipe.prompt, labels.title, labels.desc]) {
        expect(text).not.toMatch(/[\u2013\u2014]/);
      }
    }
  });
});
