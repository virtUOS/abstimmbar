// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { fmtPct } from "../format";
import { useCountUp, useReducedMotion } from "./motion";

/** A number that counts up to `value` (e.g. a percentage on reveal). Without
 *  a `suffix` it is a percentage in the UI language's style (#293). */
export default function CountUp({
  value,
  animate = true,
  delay = 0,
  suffix,
}: {
  value: number;
  animate?: boolean;
  delay?: number;
  suffix?: string;
}) {
  const reduced = useReducedMotion();
  const shown = useCountUp(value, { animate: animate && !reduced, delay });
  return (
    <span className="tabular-nums">
      {suffix == null ? fmtPct(shown) : `${shown}${suffix}`}
    </span>
  );
}
