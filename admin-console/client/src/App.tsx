import { Toaster } from "@/components/ui/sonner";
import NotFound from "@/pages/NotFound";
import { Route, Switch } from "wouter";
import ErrorBoundary from "./components/ErrorBoundary";
import { ThemeProvider } from "./contexts/ThemeContext";
import ContentPolicies from "./pages/ContentPolicies";
import Home from "./pages/Home";
import OperationsGuide from "./pages/OperationsGuide";

function Router() {
  return <Switch><Route path="/" component={Home} /><Route path="/content" component={ContentPolicies} /><Route path="/runbook" component={OperationsGuide} /><Route path="/404" component={NotFound} /><Route component={NotFound} /></Switch>;
}

function App() {
  return <ErrorBoundary><ThemeProvider defaultTheme="light"><Toaster richColors position="top-center" /><Router /></ThemeProvider></ErrorBoundary>;
}

export default App;
