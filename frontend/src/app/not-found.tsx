import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-2xl py-16">
      <Card>
        <CardHeader>
          <CardTitle>Page not found</CardTitle>
          <CardDescription>
            That path doesn&apos;t exist. It may have moved during the
            Streamlit → Next.js migration.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Link href="/">
            <Button>Back to home</Button>
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}
