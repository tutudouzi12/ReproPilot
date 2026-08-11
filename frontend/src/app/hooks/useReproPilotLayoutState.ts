import { useEffect, useState } from 'react';

export function useReproPilotLayoutState() {
  const [leftPanelWidth, setLeftPanelWidth] = useState(276);
  const [isResizing, setIsResizing] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(360);
  const [isResizingSidebar, setIsResizingSidebar] = useState(false);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (isResizing) {
        const newWidth = e.clientX;
        if (newWidth > 252 && newWidth < 320) {
          setLeftPanelWidth(newWidth);
        }
      } else if (isResizingSidebar) {
        const newSidebarWidth = window.innerWidth - e.clientX;
        if (newSidebarWidth > 336 && newSidebarWidth < Math.min(420, window.innerWidth * 0.4)) {
          setSidebarWidth(newSidebarWidth);
        }
      }
    };

    const handleMouseUp = () => {
      setIsResizing(false);
      setIsResizingSidebar(false);
      document.body.style.cursor = 'default';
    };

    if (isResizing || isResizingSidebar) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = 'col-resize';
    }

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing, isResizingSidebar]);

  return {
    leftPanelWidth,
    isResizing,
    sidebarWidth,
    isResizingSidebar,
    startResizingLeftPanel: () => setIsResizing(true),
    startResizingSidebar: () => setIsResizingSidebar(true),
  };
}
