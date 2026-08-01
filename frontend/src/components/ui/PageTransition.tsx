import { useState, useEffect } from "react";
import { useLocation } from "react-router-dom";

export function PageTransition({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const [displayChildren, setDisplayChildren] = useState(children);
  const [transitionStage, setTransitionStage] = useState("enter");

  useEffect(() => {
    setTransitionStage("exit");
    const timeout = setTimeout(() => {
      setDisplayChildren(children);
      setTransitionStage("enter");
    }, 150);
    return () => clearTimeout(timeout);
  }, [location.pathname, children]);

  return (
    <div
      className={transitionStage === "enter" ? "animate-page-enter" : "animate-page-exit"}
      style={{
        animationDuration: "150ms",
        animationFillMode: "both",
      }}
    >
      {displayChildren}
    </div>
  );
}
