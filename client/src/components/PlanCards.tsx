// Free vs Premium. Everything (names, prices, limits, feature lists) comes from
// /api/config so the UI can never drift from what the server enforces.
import type { ReactNode } from "react";
import { PiCheck, PiMinus } from "react-icons/pi";
import type { AppConfig, Plan, PlanInfo } from "../api";
import { money } from "../lib/format";
import { Card } from "./Card";
import { PremiumBadge } from "./StatusBadge";

export function priceLabel(plan: PlanInfo): string {
  return Number(plan.price_cad) > 0 ? `${money(plan.price_cad, "CAD")}/month` : "Free";
}

export function limitLabel(plan: PlanInfo): string {
  return plan.monthly_receipt_limit === null
    ? "Unlimited saved receipts"
    : `Up to ${plan.monthly_receipt_limit} saved receipts per month`;
}

export function PlanCards({
  config,
  currentPlan,
  renderAction,
}: {
  config: AppConfig;
  currentPlan?: Plan;
  renderAction?: (plan: PlanInfo) => ReactNode;
}) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {config.plans.map((plan) => {
        const premium = plan.id === "PREMIUM";
        const isCurrent = currentPlan === plan.id;
        return (
          <Card
            key={plan.id}
            as="article"
            className={`flex flex-col p-5 ${premium ? "border-2 border-brand" : ""}`}
          >
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-lg font-bold text-ink">{plan.name}</h3>
              <div className="flex items-center gap-2">
                {isCurrent ? (
                  <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-900">
                    Your plan
                  </span>
                ) : null}
                {premium ? <PremiumBadge /> : null}
              </div>
            </div>
            <p className="mt-1 text-2xl font-extrabold text-ink">{priceLabel(plan)}</p>
            <p className="text-sm font-medium text-brand">{limitLabel(plan)}</p>
            <ul className="mt-3 flex-1 space-y-1.5 text-sm text-slate-700">
              {plan.features.map((f) => (
                <li key={f} className="flex gap-2">
                  <PiCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-700" aria-hidden="true" />
                  <span>{f}</span>
                </li>
              ))}
            </ul>
            {renderAction ? <div className="mt-4">{renderAction(plan)}</div> : null}
          </Card>
        );
      })}
    </div>
  );
}

/** Side-by-side feature comparison from `feature_matrix`. */
export function FeatureMatrix({ config }: { config: AppConfig }) {
  if (!config.feature_matrix?.length) return null;
  const plans = config.plans;
  const free = plans.find((p) => p.id === "FREE")?.name ?? "Free";
  const premium = plans.find((p) => p.id === "PREMIUM")?.name ?? "Premium";
  const cell = (yes: boolean, label: string) =>
    yes ? (
      <span className="inline-flex items-center justify-center">
        <PiCheck className="h-5 w-5 text-emerald-700" aria-hidden="true" />
        <span className="sr-only">{label}: included</span>
      </span>
    ) : (
      <span className="inline-flex items-center justify-center">
        <PiMinus className="h-5 w-5 text-slate-500" aria-hidden="true" />
        <span className="sr-only">{label}: not included</span>
      </span>
    );
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <table className="w-full min-w-[22rem] text-left text-sm">
        <caption className="sr-only">Free and Premium plan comparison</caption>
        <thead className="bg-slate-50 text-slate-700">
          <tr>
            <th scope="col" className="px-4 py-2.5 font-semibold">
              Feature
            </th>
            <th scope="col" className="px-4 py-2.5 text-center font-semibold">
              {free}
            </th>
            <th scope="col" className="px-4 py-2.5 text-center font-semibold">
              {premium}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {config.feature_matrix.map((row) => (
            <tr key={row.feature}>
              <th scope="row" className="px-4 py-2.5 font-normal text-slate-800">
                {row.feature}
              </th>
              <td className="px-4 py-2.5 text-center">{cell(row.free, `${row.feature} on ${free}`)}</td>
              <td className="px-4 py-2.5 text-center">
                {cell(row.premium, `${row.feature} on ${premium}`)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
