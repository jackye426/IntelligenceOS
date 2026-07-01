import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

type Params = { params: Promise<{ id: string }> };

// POST /api/accounts/[id]/interactions — append a manual note or log entry.
export async function POST(req: Request, { params }: Params) {
  const { id } = await params;
  const { type = "manual_note", body, created_by_user = "internal", source_id } = await req.json();

  if (!body) return NextResponse.json({ error: "body is required" }, { status: 400 });

  const { data, error } = await supabase
    .from("clinic_interactions")
    .insert({ clinic_account_id: id, type, body, created_by_user, source_id: source_id ?? null })
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
