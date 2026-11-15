<?php

declare(strict_types=1);

namespace Acme\Permissions;

final class Permissions
{
    /** @return list<string> */
    public function for(string $role): array
    {
        return match ($role) {
            'admin' => ['manage', 'edit', 'view'],
            'editor' => ['edit', 'view'],
            'viewer' => ['view'],
            default => throw new \InvalidArgumentException('Unknown role: ' . $role),
        };
    }
}
