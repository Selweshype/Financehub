<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('transactions', function (Blueprint $table) {
            $table->id();
            $table->foreignId('user_id')->constrained()->cascadeOnDelete();
            $table->foreignId('account_id')->constrained()->cascadeOnDelete();
            $table->foreignId('category_id')->nullable()->constrained()->nullOnDelete();
            $table->decimal('amount', 15, 2);
            $table->enum('type', ['income', 'expense']);
            $table->date('date');
            $table->string('description')->nullable();
            $table->string('payee')->nullable();
            $table->text('notes')->nullable();
            $table->boolean('is_reconciled')->default(false);
            $table->timestamps();

            $table->index(['user_id', 'date']);
            $table->index(['account_id', 'date']);
            $table->index(['user_id', 'type', 'date']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('transactions');
    }
};
