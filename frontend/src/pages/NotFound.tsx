/** 404. */

import { Link } from 'react-router-dom';
import { Compass } from 'lucide-react';
import { Button } from '@/components/ui';
import { StateShell } from '@/components/states';

export default function NotFound() {
  return (
    <div className="py-16">
      <StateShell
        icon={<Compass size={26} />}
        title="Page not found"
        description="That page doesn’t exist. Let’s get you back on track."
      >
        <Link to="/">
          <Button variant="secondary">Back to home</Button>
        </Link>
      </StateShell>
    </div>
  );
}
