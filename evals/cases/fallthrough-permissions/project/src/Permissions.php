<?php

declare(strict_types=1);

namespace Cases\FallthroughPermissions;

final class Permissions
{
    /** @return list<string> */
    public function for(string $role): array
    {
        $permissions = [];
        switch ($role) {
            case 'admin':
                $permissions[] = 'manage';
                // no break: an admin also gets everything an editor gets
            case 'editor':
                $permissions[] = 'edit';
                // no break: an editor also gets everything a viewer gets
            case 'viewer':
                $permissions[] = 'view';
                break;
            default:
                throw new \InvalidArgumentException('Unknown role: ' . $role);
        }
        return $permissions;
    }
}
