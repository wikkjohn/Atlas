import { UserRound, X } from "lucide-react";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { inputClass } from "@/components/Field";
import {
  useCreateDelegation,
  useDelegateTask,
  useDelegations,
  useDeleteDelegation,
  usePeople,
  useTaskCandidates,
} from "@/services/workflows";
import type { WorkflowTask } from "@/types/workflows";

/** Who a task is with (Phase 71): a named person, or the shared queue. */
export function AssignmentLine({ task }: { task: WorkflowTask }) {
  if (!task.assignee_id) return <p className="text-xs text-slate-500">Shared queue: anyone qualified may take it</p>;
  return (
    <p className="flex items-center gap-1 text-xs text-slate-600">
      <UserRound aria-hidden className="h-3.5 w-3.5" />
      <span>
        Assigned to <span className="font-medium">{task.assigned_to_me ? "you" : task.assignee_username}</span>
        {task.delegated_from_username && ` (from ${task.delegated_from_username})`}
      </span>
    </p>
  );
}

/** Hand an assigned task to another qualified person, least loaded first. */
export function DelegateControl({ task }: { task: WorkflowTask }) {
  const [open, setOpen] = useState(false);
  const [delegateId, setDelegateId] = useState("");
  const candidates = useTaskCandidates(open ? task.run_id : null);
  const delegate = useDelegateTask();
  if (!task.assigned_to_me) return null;
  if (!open) {
    return (
      <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>
        Delegate
      </Button>
    );
  }
  const others = (candidates.data ?? []).filter((c) => !c.assignee);
  return (
    <div className="flex flex-col items-end gap-1.5">
      <select
        aria-label={`Delegate ${task.subject ?? task.step_name} to`}
        className="w-56 rounded-lg border border-slate-200 px-2 py-1 text-sm"
        value={delegateId}
        onChange={(e) => setDelegateId(e.target.value)}
      >
        <option value="">Choose a colleague…</option>
        {others.map((c) => (
          <option key={c.user_id} value={c.user_id}>
            {c.display_name} ({c.open_tasks} open)
          </option>
        ))}
      </select>
      <div className="flex gap-1.5">
        <Button
          size="sm"
          disabled={!delegateId || delegate.isPending}
          onClick={() => delegate.mutate({ runId: task.run_id, delegateId }, { onSuccess: () => setOpen(false) })}
        >
          Hand over
        </Button>
        <Button size="sm" variant="secondary" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
      <ErrorMessage error={candidates.error ?? delegate.error} />
    </div>
  );
}

/** Out of office: while a delegation runs, new tasks for you go to your delegate. */
export function OutOfOfficePanel() {
  const delegations = useDelegations();
  const create = useCreateDelegation();
  const remove = useDeleteDelegation();
  const [search, setSearch] = useState("");
  const people = usePeople(search);
  const [form, setForm] = useState({ delegate_id: "", starts_on: "", ends_on: "", reason: "" });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(form, { onSuccess: () => setForm({ delegate_id: "", starts_on: "", ends_on: "", reason: "" }) });
  };
  return (
    <section aria-label="Out of office" className="mb-5 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-900">Out of office</h2>
      <p className="mb-3 text-xs text-slate-500">While a delegation runs, tasks assigned to you by name go to your delegate.</p>
      {delegations.data && delegations.data.length > 0 && (
        <ul className="mb-3 space-y-1 text-sm">
          {delegations.data.map((d) => (
            <li key={d.id} className="flex items-center justify-between gap-2">
              <span>
                {d.username} → {d.delegate_username}, {d.starts_on} to {d.ends_on}
                {d.reason && ` · ${d.reason}`}
                {d.active && <span className="font-medium text-emerald-700"> · active</span>}
              </span>
              <button
                type="button"
                aria-label={`End the delegation to ${d.delegate_username}`}
                className="text-slate-500 hover:text-rose-700"
                onClick={() => remove.mutate(d.id)}
              >
                <X aria-hidden className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={submit} className="flex flex-wrap items-end gap-2 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-slate-600">Find a colleague</span>
          <input className={inputClass} value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name or username" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-slate-600">Delegate</span>
          <select
            className={inputClass}
            value={form.delegate_id}
            onChange={(e) => setForm({ ...form, delegate_id: e.target.value })}
            required
          >
            <option value="">Choose…</option>
            {(people.data ?? []).map((p) => (
              <option key={p.user_id} value={p.user_id}>
                {p.display_name} ({p.username})
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-slate-600">From</span>
          <input type="date" className={inputClass} value={form.starts_on} onChange={(e) => setForm({ ...form, starts_on: e.target.value })} required />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-slate-600">To</span>
          <input type="date" className={inputClass} value={form.ends_on} onChange={(e) => setForm({ ...form, ends_on: e.target.value })} required />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-slate-600">Reason</span>
          <input className={inputClass} value={form.reason} maxLength={200} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
        </label>
        <Button type="submit" size="sm" disabled={create.isPending}>
          Delegate my tasks
        </Button>
      </form>
      <ErrorMessage error={create.error ?? remove.error ?? delegations.error} className="mt-2" />
    </section>
  );
}
