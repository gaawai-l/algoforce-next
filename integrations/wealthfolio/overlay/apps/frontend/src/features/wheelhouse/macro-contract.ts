import { z } from "zod";
import type { components } from "./api-schema";

export type MacroWatch = components["schemas"]["MacroWatch"];

export const macroWatchSchema: z.ZodType<MacroWatch, z.ZodTypeDef, unknown> =
  z.object({
    checked_at: z.string().datetime({ offset: true }),
    fomc: z
      .object({
        decision_at: z.string().datetime({ offset: true }),
        meeting: z.string(),
        projections: z.boolean(),
      })
      .nullable(),
    fomc_error: z.string().nullable(),
    spread: z
      .object({
        day: z.string().date(),
        ten_year: z.number(),
        one_year: z.number(),
        spread: z.number(),
        inverted: z.boolean(),
        history: z.array(
          z.object({ day: z.string().date(), spread: z.number() }),
        ),
      })
      .nullable(),
    spread_error: z.string().nullable(),
  });
