// App.jsx — placeholder.
//
// This file is the assembly point for the cloned page. In v3 it is rewritten
// deterministically by the `assemble_project` MCP tool, which imports every
// generated section component from `./components/sections/{namespace}/` and
// renders them in order.
//
// Section subagents must NOT edit this file directly; they only write into
// their own `src/components/sections/{namespace}/` directory.
//
// Example of what the assembled file looks like:
//
//   import HeroSection from "./components/sections/hero/HeroSection.jsx";
//   import FeaturesSection from "./components/sections/features/FeaturesSection.jsx";
//
//   export default function App() {
//     return (
//       <>
//         <HeroSection />
//         <FeaturesSection />
//       </>
//     );
//   }

export default function App() {
  return (
    <main className="min-h-screen flex items-center justify-center text-gray-500">
      <p>Base template — sections will be assembled here.</p>
    </main>
  );
}
