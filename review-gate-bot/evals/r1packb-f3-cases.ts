/** R1-F3: f3-02..06 bugs + f3-ctrl-01..03 (excludes f3-01 report-only). */
export const R1PACKB_F3_FIXTURES = [
  ...["02", "03", "04", "05", "06"].map((n) => `r1b-f3-${n}`),
  ...["01", "02", "03"].map((n) => `r1b-f3-ctrl-${n}`),
] as const;
