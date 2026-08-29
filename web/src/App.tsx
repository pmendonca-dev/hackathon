import { StoreProvider, useStore } from './domain/store';
import { Sidebar, MobileNav } from './components/Shell';
import { Toasts } from './components/Toasts';
import { Overview } from './pages/Overview';
import { Mandates } from './pages/Mandates';
import { Payments } from './pages/Payments';
import { AgentActivity } from './pages/AgentActivity';
import { MerchantView } from './pages/MerchantView';
import { Ledger } from './pages/Ledger';
import { Disputes } from './pages/Disputes';
import { JudgeConsole } from './pages/JudgeConsole';

function Router() {
  const { state } = useStore();
  switch (state.route) {
    case 'mandates':  return <Mandates />;
    case 'payments':  return <Payments />;
    case 'agent':     return <AgentActivity />;
    case 'merchant':  return <MerchantView />;
    case 'ledger':    return <Ledger />;
    case 'disputes':  return <Disputes />;
    case 'judge':     return <JudgeConsole />;
    default:          return <Overview />;
  }
}

export default function App() {
  return (
    <StoreProvider>
      <div className="flex h-full">
        <Sidebar />
        <main className="flex min-w-0 flex-1 flex-col overflow-y-auto">
          <MobileNav />
          <Router />
        </main>
      </div>
      <Toasts />
    </StoreProvider>
  );
}
