<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Attributes\Fillable;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

#[Fillable(['user_id', 'account_id', 'category_id', 'amount', 'type', 'date', 'description', 'payee', 'notes', 'is_reconciled'])]
class Transaction extends Model
{
    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class);
    }

    public function account(): BelongsTo
    {
        return $this->belongsTo(Account::class);
    }

    public function category(): BelongsTo
    {
        return $this->belongsTo(Category::class);
    }

    protected function casts(): array
    {
        return [
            'amount'        => 'decimal:2',
            'date'          => 'date',
            'is_reconciled' => 'boolean',
        ];
    }
}
