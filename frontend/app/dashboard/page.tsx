import { getDashboardData } from "@/lib/api";
import { redirectIfUnauthorized } from "../authRedirect";
import { DashboardExperience } from "../DashboardExperience";

export default async function DashboardPage() {
  let data;
  try {
    data = await getDashboardData();
  } catch (error) {
    redirectIfUnauthorized(error);
  }
  return <DashboardExperience data={data} />;
}
