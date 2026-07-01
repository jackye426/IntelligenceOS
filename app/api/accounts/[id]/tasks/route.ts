import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

type Params = { params: Promise<{ id: string }> };

// GET /api/accounts/[id]/tasks — list open tasks for this account.
export async function GET(_req: Request, { params }: Params) {
  const { id } = await params;

  const { data, error } = await supabase
    .from("account_tasks")
    .select("*")
    .eq("clinic_account_id", id)
    .neq("status", "cancelled")
    .order("due_at", { ascending: true });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

// POST /api/accounts/[id]/tasks — create a new task.
export async function POST(req: Request, { params }: Params) {
  const { id } = await params;
  const { title, owner_user = "internal", due_at } = await req.json();

  if (!title) return NextResponse.json({ error: "title is required" }, { status: 400 });

  const { data, error } = await supabase
    .from("account_tasks")
    .insert({ clinic_account_id: id, title, owner_user, due_at: due_at ?? null })
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}

// PATCH /api/accounts/[id]/tasks — mark a task done or cancelled.
export async function PATCH(req: Request, { params }: Params) {
  const { id } = await params;
  const { task_id, status } = await req.json();

  if (!task_id || !["done", "cancelled"].includes(status)) {
    return NextResponse.json({ error: "task_id and valid status required" }, { status: 400 });
  }

  const { data, error } = await supabase
    .from("account_tasks")
    .update({
      status,
      completed_at: status === "done" ? new Date().toISOString() : null,
    })
    .eq("id", task_id)
    .eq("clinic_account_id", id)
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}
