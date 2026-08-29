import { MissionProvider } from "./components/MissionProvider";
import MissionControlPage from "./components/MissionControlPage";

export default function Home() {
  return (
    <MissionProvider>
      <MissionControlPage />
    </MissionProvider>
  );
}
