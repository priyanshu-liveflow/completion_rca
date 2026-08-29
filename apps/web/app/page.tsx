import MissionRuntime from "./components/MissionRuntime";
import { MissionMode } from "./lib/types";

interface HomePageProps {
  searchParams: Promise<{ live?: string | string[] | undefined }>;
}

export default async function Home({ searchParams }: HomePageProps) {
  const { live } = await searchParams;
  const mode: MissionMode = live === "1" ? "live" : "fixture";

  return <MissionRuntime mode={mode} />;
}
