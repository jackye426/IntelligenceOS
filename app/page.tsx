import { redirect } from "next/navigation";

// Root redirects to the accounts view (the default landing page).
export default function RootPage() {
  redirect("/accounts");
}
